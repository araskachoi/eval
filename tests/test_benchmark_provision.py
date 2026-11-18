from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import isolated


class BenchmarkProvisionTests(unittest.TestCase):
    def test_only_existing_rootless_unmounted_machine_is_started(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(isolated, 'RUNTIME', Path(directory)):
            config = isolated.machine_config_path()
            config.parent.mkdir(parents=True)
            machine = {'Mounts': [], 'HostUser': {'Rootful': False}, 'Resources': {'USBs': []}}
            config.write_text(json.dumps(machine))
            stopped = json.dumps([{'Rootful': False, 'State': 'stopped'}]).encode()
            running = json.dumps([{'Rootful': False, 'State': 'running'}]).encode()
            with patch.object(isolated, 'command', side_effect=[stopped, b'', running]) as command:
                isolated.start_machine()
                command.assert_called_with('machine', 'start', '--update-connection=false',
                                           isolated.MACHINE, timeout=60)
                isolated.start_machine()
                self.assertEqual(command.call_count, 3)
            with patch.object(isolated, 'command', side_effect=[stopped, RuntimeError('busy'), running]):
                isolated.start_machine()
            socket_error = RuntimeError('unable to connect to "gvproxy" socket')
            with patch.object(isolated, 'command',
                              side_effect=[stopped, socket_error, stopped, b'']) as command:
                isolated.start_machine()
                self.assertEqual(command.call_count, 4)
            with patch.object(isolated, 'command',
                              side_effect=[stopped, RuntimeError('permission denied'), stopped]) as command:
                with self.assertRaisesRegex(RuntimeError, 'permission denied'):
                    isolated.start_machine()
                self.assertEqual(command.call_count, 3)
            machine['Mounts'].append({'Source': '/synthetic-example'})
            config.write_text(json.dumps(machine))
            with patch.object(isolated, 'command') as command:
                with self.assertRaisesRegex(RuntimeError, 'no shared host mounts'):
                    isolated.start_machine()
                command.assert_not_called()

    def test_provision_requires_pinned_image_and_empty_volume_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            image = runtime / 'dummy-image'
            image.write_bytes(b'dummy')
            policy = runtime / 'config' / 'containers' / 'containers.conf'

            def podman(*args, **kwargs):
                if args == ('--version',):
                    return b'podman version 6.1.4\n'
                self.assertEqual(args[:5], ('machine', 'init', '--provider', 'applehv', '--rootful=false'))
                self.assertEqual(policy.read_text(), '[machine]\nvolumes = []\n')
                self.assertEqual(args[-3:], ('--image', str(image.resolve()), isolated.MACHINE))
                config = isolated.machine_config_path()
                config.parent.mkdir(parents=True)
                config.write_text(json.dumps({'Mounts': [], 'HostUser': {'Rootful': False},
                                              'Resources': {'USBs': []}}))
                return b''

            with patch.object(isolated, 'RUNTIME', runtime), patch.object(
                isolated.platform, 'system', return_value='Darwin'
            ), patch.object(isolated.platform, 'machine', return_value='arm64'), patch.object(
                isolated, 'command', side_effect=podman
            ) as command:
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    isolated.provision(image, '0' * 64)
                command.assert_not_called()
                self.assertFalse(policy.exists())
                self.assertEqual(isolated.provision(image, sha256(b'dummy').hexdigest())['host_mounts'], 0)
                with self.assertRaisesRegex(ValueError, 'already'):
                    isolated.provision(image, sha256(b'dummy').hexdigest())
