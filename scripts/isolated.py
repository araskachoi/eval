#!/usr/bin/env python3
"""Trusted launcher. Test payloads are copied, never mounted or run on the host."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import selectors
from pathlib import Path
import subprocess
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MACHINE = 'eval-sandbox'
BIN = ROOT / '.runtime/podman-package/podman.pkg/Payload/podman/bin'
PODMAN = BIN / 'podman'
IMAGE = 'docker.io/library/python@sha256:29434a59c93070e470f84663e4289026e04644ea44b5220ef7e07d653318ca1f'


def environment():
    # No model keys, user config, SSH agents, or application credentials are inherited.
    # Preserve the actual home for the trusted runtime client; never forward it to workloads.
    retained={key:os.environ[key] for key in ('HOME',) if key in os.environ}
    return {**retained,'PATH':str(BIN)+':/usr/bin:/bin','XDG_CONFIG_HOME':str(ROOT / '.runtime/config'),
            'XDG_DATA_HOME':str(ROOT / '.runtime/data'),'LANG':'C.UTF-8', 'CONTAINERS_MACHINE_PROVIDER':'applehv'}


def command(*args, **kwargs):
    result = subprocess.run([str(PODMAN),*args],env=environment(),capture_output=True,timeout=kwargs.pop('timeout',30),**kwargs)
    if result.returncode:
        # The launcher supplies no credentials in argv; bounded runtime diagnostics aid recovery.
        diagnostic=result.stderr.decode(errors='replace')[-4000:]
        raise RuntimeError('Podman operation failed; no host-execution fallback is permitted\n'+diagnostic)
    return result.stdout


def verify_machine():
    machine = json.loads(command('machine','inspect',MACHINE))[0]
    config_path = ROOT / '.runtime/config/containers/podman/machine/applehv' / (MACHINE+'.json')
    config = json.loads(config_path.read_text())
    if config.get('Mounts') != [] or config.get('HostUser',{}).get('Rootful') is not False or machine.get('Rootful') is not False or machine.get('State') != 'running':
        raise RuntimeError('VM must be running, rootless, and have no shared host mounts')
    info = json.loads(command('--connection',MACHINE,'info','--format','json'))
    if info['host']['security'].get('rootless') is not True:
        raise RuntimeError('Effective engine is not rootless')
    if info['host']['security'].get('seccompEnabled') is not True:
        raise RuntimeError('Seccomp is not enabled')
    mounts = json.loads(command('machine','ssh',MACHINE,'findmnt','--json',timeout=10))
    pending=list(mounts.get('filesystems',[]))
    while pending:
        mount=pending.pop()
        if mount.get('fstype') in {'virtiofs','9p'}:
            raise RuntimeError('Effective guest host-sharing mounts found')
        pending.extend(mount.get('children',[]))
    if config.get('Resources',{}).get('USBs') != []:
        raise RuntimeError('Guest device passthrough is prohibited')
    return {'machine':MACHINE,'rootless':True,'host_mounts':0}


def verify_container(inspect):
    host, config = inspect['HostConfig'],inspect['Config']
    if config.get('User') != '1000:1000' or host.get('Privileged') or host.get('NetworkMode') != 'none':
        raise RuntimeError('Workload user/network/privileges failed preflight')
    if not host.get('ReadonlyRootfs') or host.get('CapAdd'):
        raise RuntimeError('Read-only/capability boundary failed')
    if 'no-new-privileges' not in host.get('SecurityOpt',[]):
        raise RuntimeError('No-new-privileges is missing')
    if host.get('PidMode') == 'host' or host.get('IpcMode') == 'host' or host.get('Devices'):
        raise RuntimeError('Host namespaces/devices are prohibited')
    if inspect.get('EffectiveCaps') or inspect.get('BoundingCaps'):
        raise RuntimeError('Workload retains capabilities')
    if host.get('Memory',0) != 536870912 or host.get('PidsLimit') != 64:
        raise RuntimeError('Resource limits are missing')
    if host.get('NanoCpus',0) != 1000000000:
        raise RuntimeError('CPU limit is missing')
    mounts = inspect.get('Mounts',[])
    if any(m.get('Type') != 'tmpfs' or m.get('Destination') not in {'/work','/tmp'} for m in mounts):
        raise RuntimeError('Unexpected workload mounts')
    if host.get('Binds'):
        raise RuntimeError('Host bind mounts prohibited')


def workload(name,payload):
    process=subprocess.Popen([str(PODMAN),'--connection',MACHINE,'start','--attach','--interactive',name],
                             env=environment(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    deadline=time.monotonic()+90
    output=bytearray()
    try:
        os.set_blocking(process.stdin.fileno(),False)
        sent=0
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin,selectors.EVENT_WRITE)
            selector.register(process.stdout,selectors.EVENT_READ)
            selector.register(process.stderr,selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic()>deadline:
                    raise RuntimeError('Workload timed out')
                for key,_ in selector.select(.25):
                    if key.fileobj is process.stdin:
                        sent+=os.write(process.stdin.fileno(),payload[sent:sent+16384])
                        if sent==len(payload):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                        continue
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output)>1024*1024:
                            raise RuntimeError('Workload output capacity exceeded')
        if process.wait(timeout=5):
            raise RuntimeError('Contained tests failed:\n'+output.decode(errors='replace')[-12000:])
        return output.decode(errors='replace')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
        if not process.stdin.closed:
            process.stdin.close()


BOOTSTRAP = r'''
import io,json,os,pathlib,resource,subprocess,sys,tarfile
assert os.getuid()==1000 and pathlib.Path('/run/.containerenv').is_file()
assert '0000000000000000' in next(x.split(':',1)[1].strip() for x in pathlib.Path('/proc/self/status').read_text().splitlines() if x.startswith('CapEff:'))
assert next(x.split(':',1)[1].strip() for x in pathlib.Path('/proc/self/status').read_text().splitlines() if x.startswith('NoNewPrivs:'))=='1'
assert set(os.listdir('/sys/class/net'))=={'lo'}
resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024*1024,16*1024*1024))
data=sys.stdin.buffer.read(4*1024*1024+1)
assert len(data)<=4*1024*1024
with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
 for member in archive:
  name=pathlib.PurePosixPath(member.name)
  assert member.isfile() and not name.is_absolute() and '..' not in name.parts and member.size<1024*1024
  destination=pathlib.Path('/work')/str(name)
  destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(archive.extractfile(member).read())
result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd='/work',timeout=60)
if result.returncode==0:
 from codex_eval.core import Store
 from codex_eval.scenarios import scenario
 from codex_eval.magen import MagenGate
 store=Store('/tmp/fixture-metrics')
 bundles=[]
 for name in ('desktop','multi','subagents','repair','blocked','partial'):
  reports=scenario(store,name,MagenGate.isolated_local())
  for report in reports:
   record=report['recording']
   events=[json.loads(row[0]) for row in store.db.execute('SELECT data FROM events WHERE recording_id=? ORDER BY occurred,event_id',(record['id'],))]
   bundles.append({'scenario':name,'recording':record,'events':events})
 store.close()
 print('EVAL_FIXTURES:'+json.dumps(bundles,separators=(',',':')),flush=True)
raise SystemExit(result.returncode)
'''


def bundle(magen):
    output = io.BytesIO()
    digest = hashlib.sha256()
    with tarfile.open(fileobj=output,mode='w:') as archive:
        files = [(p,p.relative_to(ROOT).as_posix()) for folder in ('codex_eval','tests','scripts') for p in sorted((ROOT / folder).rglob('*')) if p.is_file() and p.suffix in {'.py','.html','.js','.css'}]
        if magen:
            files.extend((magen / 'gateway' / filename, 'gateway/' + filename) for filename in ('detectors.py','types.py'))
        for path,name in files:
            if path.is_symlink() or '__pycache__' in path.parts:
                raise RuntimeError('Unexpected symlink/cache in staged source')
            data = path.read_bytes()
            digest.update(name.encode()+b'\0'+data)
            member = tarfile.TarInfo(name)
            member.size,member.mode = len(data),0o600
            archive.addfile(member,io.BytesIO(data))
        if magen:
            member=tarfile.TarInfo('gateway/__init__.py')
            member.size=0
            archive.addfile(member,io.BytesIO())
    return output.getvalue(),digest.hexdigest()


def run_tests(magen):
    evidence = verify_machine()
    image = json.loads(command('--connection',MACHINE,'image','inspect',IMAGE))[0]
    image_id = image['Id']
    if not re.fullmatch(r'(sha256:)?[0-9a-f]{64}',image_id):
        raise RuntimeError('Image identity unavailable; stage a reviewed image first')
    payload,digest = bundle(magen)
    name='eval-test-'+uuid.uuid4().hex
    command('--connection',MACHINE,'create','--name',name,'--network','none','--user','1000:1000',
            '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64',
            '--memory','512m','--cpus','1','--ulimit','nofile=256:256','--ulimit','core=0:0',
            '--tmpfs','/work:rw,nosuid,nodev,noexec,size=64m,mode=1777',
            '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777','--workdir','/work',
            '--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONPATH=/work',
            '--http-proxy=false','--entrypoint','python','--interactive',image_id,'-c',BOOTSTRAP)
    try:
        inspect=json.loads(command('--connection',MACHINE,'inspect',name))[0]
        verify_container(inspect)
        evidence.update(image_id=image_id,source_digest=digest,network='none',uid=1000,mode='simulated acceptance; not a live model benchmark')
        print(json.dumps(evidence,indent=2),flush=True)
        output=workload(name,payload)
        fixture_line=None
        for line in output.splitlines():
            if line.startswith('EVAL_FIXTURES:'):
                fixture_line=line[len('EVAL_FIXTURES:'):]
            else:
                print(line)
        if fixture_line:
            export_fixtures(json.loads(fixture_line))
    finally:
        command('--connection',MACHINE,'rm','--force',name)


def export_fixtures(bundles):
    """Export validated metrics only; never extract workload-generated files."""
    import sys
    sys.path.insert(0,str(ROOT))
    from codex_eval.core import Store, identifier, normalize, timestamp
    from codex_eval.report import render
    if not isinstance(bundles,list) or len(bundles)!=7:
        raise RuntimeError('Unexpected fixture export')
    approved={'desktop','multi','subagents','repair','blocked','partial'}
    validated=[]
    for bundle in bundles:
        if bundle['scenario'] not in approved or len(bundle['events'])>100:
            raise RuntimeError('Unexpected fixture export')
        record=bundle['recording']
        identifier(record['thread_id']); identifier(record['task_id'])
        start,end=timestamp(record['started']),timestamp(record['finished'])
        if not time.time()-3600<=start<=end<=time.time():
            raise RuntimeError('Fixture window is invalid')
        validated.append((bundle['scenario'],record,[normalize(e) for e in bundle['events']]))
    destination=ROOT/'artifacts'
    destination.mkdir(mode=0o700,exist_ok=True)
    tasks={}
    store=Store(ROOT/'.runtime/acceptance-metrics')
    for scenario_name,record,events in validated:
        new=store.start(record['thread_id'],task_id=tasks.get(record['task_id']),source='controlled-simulation',now=record['started'],sample_case=scenario_name)
        tasks[record['task_id']]=new['task_id']
        for event in events:
            store.ingest({'recording_id':new['id'],'event':event})
        report=store.finish(now=record['finished'])
        filename=destination/(scenario_name+'-'+new['id'][:8]+'.html')
        descriptor=os.open(filename,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'w') as output:
            output.write(render(report))
    store.close()
    print('Exported seven simulated acceptance reports to artifacts/; no raw payloads exported.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['preflight','test','hold','stage'])
    parser.add_argument('--magen',type=Path)
    args=parser.parse_args()
    try:
        if args.operation=='hold':
            print(command('machine','start',MACHINE,timeout=60).decode(),flush=True)
            try:
                while True:
                    time.sleep(30)
            finally:
                command('machine','stop',MACHINE)
        elif args.operation=='stage':
            verify_machine()
            command('--connection',MACHINE,'pull',IMAGE,timeout=180)
            image=json.loads(command('--connection',MACHINE,'image','inspect',IMAGE))[0]
            print(json.dumps({'image_id':image['Id'],'repo_digests':image.get('RepoDigests',[])},indent=2))
        elif args.operation=='preflight':
            print(json.dumps(verify_machine(),indent=2))
        else:
            run_tests(args.magen)
    except KeyboardInterrupt:
        pass
    except (RuntimeError,ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:
        parser.exit(1,f'Isolation gate stopped execution: {exc}\n')


if __name__=='__main__':
    main()
