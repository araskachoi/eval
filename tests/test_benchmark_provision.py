from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import isolated


class BenchmarkProvisionTests(unittest.TestCase):
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
