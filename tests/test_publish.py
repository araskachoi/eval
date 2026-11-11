import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
import unittest

from codex_eval.__main__ import control
from codex_eval.core import Store, new_id
from codex_eval.server import Service
from codex_eval.version import VERSION
from scripts import publish_app as publisher

ROOT = Path(__file__).resolve().parents[1]
PROOF = {'passed':True, 'runner':'isolated unit-test fixture'}


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.releases=self.base/'releases'
        self.releases.mkdir(mode=0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_is_versioned_private_and_excludes_runtime_data(self):
        release=publisher.make_release(ROOT,self.releases,PROOF)
        manifest=publisher.verify_release(release)
        self.assertEqual(manifest['version'],VERSION)
        self.assertEqual(manifest['release_id'],release.name)
        self.assertEqual((release/'codex_eval/core.py').stat().st_mode & 0o777,0o600)
        self.assertFalse((release/'.runtime').exists())
        self.assertFalse((release/'.git').exists())
        self.assertFalse((release/'tests').exists())
        self.assertEqual(publisher.make_release(ROOT,self.releases,PROOF),release)
        (release/'codex_eval/web/app.css').write_text('changed after release')
        with self.assertRaises(ValueError): publisher.verify_release(release)

    def test_symlink_source_is_refused(self):
        root=self.base/'source'
        (root/'codex_eval').mkdir(parents=True)
        (root/'codex_eval/secret.py').symlink_to(ROOT/'codex_eval/core.py')
        with self.assertRaises(ValueError): publisher.source_files(root)

    def test_prepare_blocks_new_recordings_and_refuses_active_recording(self):
        state=self.base/'state'
        store=Store(state)
        store.close()
        service=Service(state)
        service.control({'action':'prepare_update'})
        with self.assertRaises(ValueError): service.control({'action':'on','thread_id':new_id()})
        with self.assertRaises(ValueError): service.control({'action':'record','thread_id':new_id()})
        service.control({'action':'cancel_update'})
        service.control({'action':'on','thread_id':new_id()})
        with self.assertRaises(ValueError): service.control({'action':'prepare_update'})
        store=Store(state)
        self.assertIsNone(store.list()[0]['finished'])
        store.close()

    def test_database_compatibility_is_checked_without_downgrade(self):
        state=self.base/'state'
        store=Store(state)
        store.db.execute('PRAGMA user_version=99')
        store.close()
        with self.assertRaises(ValueError): publisher.check_database(state,{'schema_versions':[0,1]})
        db=sqlite3.connect(state/'metrics.sqlite3')
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)
        db.close()

    def test_recorded_version_is_preserved_and_legacy_is_unknown(self):
        store=Store(self.base/'state')
        record=store.start(new_id())
        report=store.finish()
        self.assertEqual(report['recording']['application']['version'],VERSION)
        store.db.execute('DELETE FROM recording_builds WHERE recording_id=?',(record['id'],))
        store.db.commit()
        self.assertIsNone(store.report(record['id'])['recording']['application'])
        store.close()

    def test_global_skill_changes_are_not_silently_overwritten(self):
        cfg={'skills_dir':str(self.base/'skills')}
        before=publisher.read_skill(cfg)
        self.assertEqual(publisher.hashes(before),dict.fromkeys(publisher.SKILL_FILES))
        publisher.atomic(self.base/'skills/record/SKILL.md',b'customized')
        self.assertNotEqual(publisher.hashes(publisher.read_skill(cfg)),publisher.hashes(before))


class ReleaseActivationTests(unittest.TestCase):
    def test_publish_rollback_and_failed_start_preserve_data_and_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            app=base/'app';app.mkdir(mode=0o700)
            releases=app/'releases';releases.mkdir(mode=0o700)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            cfg=dict(state=str(base/'state'),skills_dir=str(base/'skills'),python=sys.executable,port=port)
            state=Path(cfg['state'])
            store=Store(state);store.close()
            first=publisher.make_release(ROOT,releases,PROOF)
            cfg=publisher.activate(first,cfg,app,reserved=False)
            try:
                thread=new_id()
                record=control(state,{'action':'on','thread_id':thread})
                with self.assertRaises(ValueError): publisher.prepare(state)
                original=control(state,{'action':'off'})
                self.assertEqual(original['recording']['application']['release_id'],first.name)
                source=base/'source'
                shutil.copytree(first,source)
                with (source/'codex_eval/web/app.css').open('a') as out: out.write('\n/* next checked build */\n')
                second=publisher.make_release(source,releases,PROOF)
                self.assertNotEqual(first.name,second.name)
                cfg=publisher.activate(second,cfg,app,reserved=publisher.prepare(state))
                self.assertEqual(control(state,{'action':'version'})['release_id'],second.name)
                saved=control(state,{'action':'report','recording_id':record['id']})
                self.assertEqual(saved['recording']['application']['release_id'],first.name)
                cfg=publisher.activate(first,cfg,app,reserved=publisher.prepare(state))
                self.assertEqual(control(state,{'action':'version'})['release_id'],first.name)
                skill_before=publisher.read_skill(cfg)
                with (source/'codex_eval/server.py').open('a') as out:out.write('\nraise RuntimeError("isolated startup failure fixture")\n')
                broken=publisher.make_release(source,releases,PROOF)
                with self.assertRaises(ValueError): publisher.activate(broken,cfg,app,reserved=publisher.prepare(state))
                self.assertEqual(control(state,{'action':'version'})['release_id'],first.name)
                self.assertEqual(publisher.read_skill(cfg),skill_before)
                self.assertEqual(json.loads((app/'install.json').read_text())['active'],first.name)
                saved=control(state,{'action':'report','recording_id':record['id']})
                self.assertEqual(saved['recording']['id'],record['id'])
            finally:
                if publisher.collector_status(state):
                    publisher.prepare(state);publisher.stop_collector(state)
