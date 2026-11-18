import copy
import os
from pathlib import Path
import unittest

from _environment import isolated_only


class IsolationTests(unittest.TestCase):
    @isolated_only
    def test_effective_workload_boundary(self):
        self.assertEqual(os.getuid(),1000)
        status=Path('/proc/self/status').read_text()
        self.assertIn('NoNewPrivs:\t1',status)
        self.assertIn('CapEff:\t0000000000000000',status)
        self.assertEqual(set(os.listdir('/sys/class/net')),{'lo'})
        for path in ('/Users','/var/run/docker.sock','/run/podman/podman.sock'):
            self.assertFalse(Path(path).exists())
        for key in ('OPENAI_API_KEY','SSH_AUTH_SOCK','DOCKER_HOST','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY'):
            self.assertNotIn(key,os.environ)
        with self.assertRaises(OSError):
            Path('/forbidden-test-write').write_text('synthetic only')

    def test_launcher_rejects_weakened_container(self):
        from scripts import isolated as launcher
        good={'Config':{'User':'1000:1000'},'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,
              'SecurityOpt':['no-new-privileges'],'Memory':536870912,'PidsLimit':64,'NanoCpus':1000000000},'Mounts':[]}
        launcher.verify_container(good)
        for key,value in [('NetworkMode','host'),('Privileged',True),('Binds',['/host:/host']),('ReadonlyRootfs',False),('SecurityOpt',[]),('PidsLimit',0),('CapAdd',['SYS_ADMIN'])]:
            changed=copy.deepcopy(good)
            changed['HostConfig'][key]=value
            with self.assertRaises(RuntimeError): launcher.verify_container(changed)
