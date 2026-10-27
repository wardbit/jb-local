import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ProjectTests(unittest.TestCase):
    def test_cli_is_available(self):
        result = subprocess.run([sys.executable, str(ROOT / 'jb.py'), '--help'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        import jb
        self.jb = jb
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bundle = self.root / 'bundle'
        names = ['ja-netfilter.jar', 'license.key']
        names += ['plugins/' + n + '.jar' for n in ('dns', 'native', 'power', 'url', 'hideme', 'privacy')]
        names += ['config/' + n + '.conf' for n in ('dns', 'native', 'power', 'url')]
        files = {}
        for name in names:
            data = ('inert test fixture: ' + name).encode()
            path = self.bundle / 'vendor' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            files[name] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        (self.bundle / 'manifest.json').write_text(json.dumps({'schema': 1, 'files': files}), encoding='utf-8')
        self.state = self.root / 'state'
        self.config = self.root / 'config' / 'IntelliJIdea2026.2'
        self.config.mkdir(parents=True)
        self.vm = self.config / 'idea64.exe.vmoptions'
        self.original = b'-Xmx4096m\r\n-javaagent:C:/tools/monitor.jar\r\n'
        self.vm.write_bytes(self.original)
        self.key = self.config / 'idea.key'
        self.key.write_bytes(b'original-license')

    def plan(self):
        target = self.jb.make_target(self.config, 'Windows', 'idea', None, None, {})
        return self.jb.make_plan([target], self.bundle, self.state)

    def test_bundle_is_complete_and_modified_jar_is_rejected(self):
        import shutil
        payload, identity = self.jb.load_bundle(self.bundle)
        self.assertIn('ja-netfilter.jar', payload)
        self.assertIn('license.key', payload)
        self.assertEqual(len(identity), 64)
        copy = self.root / 'copy'
        shutil.copytree(self.bundle / 'vendor', copy / 'vendor')
        shutil.copy2(self.bundle / 'manifest.json', copy / 'manifest.json')
        (copy / 'vendor/ja-netfilter.jar').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.jb.load_bundle(copy)

    def test_unlisted_plugin_is_rejected(self):
        import shutil
        copy = self.root / 'copy'
        shutil.copytree(self.bundle / 'vendor', copy / 'vendor')
        shutil.copy2(self.bundle / 'manifest.json', copy / 'manifest.json')
        (copy / 'vendor/plugins/extra.jar').write_bytes(b'extra')
        with self.assertRaises(ValueError):
            self.jb.load_bundle(copy)

    def test_all_platform_roots(self):
        home = self.root
        expected = {
            'Windows': (home / 'AppData/Roaming/JetBrains', home / 'AppData/Local/JetBrains'),
            'Darwin': (home / 'Library/Application Support/JetBrains', home / 'Library/Caches/JetBrains'),
            'Linux': (home / '.config/JetBrains', home / '.cache/JetBrains'),
        }
        for system, roots in expected.items():
            with self.subTest(system=system):
                self.assertEqual(self.jb.platform_roots(system, home, {}), roots)
        self.assertEqual(self.jb.platform_roots('Linux', home, {'XDG_CONFIG_HOME': str(home / 'xdg')})[0], home / 'xdg/JetBrains')

    def test_platform_discovery_seeds_distribution_defaults(self):
        names = {'Windows': 'idea64.exe.vmoptions', 'Linux': 'idea64.vmoptions', 'Darwin': 'idea.vmoptions'}
        for system, name in names.items():
            with self.subTest(system=system):
                home = self.root / system
                conf, cache = self.jb.platform_roots(system, home, {})
                cfg = conf / 'IntelliJIdea2026.2'
                cfg.mkdir(parents=True)
                info = cache / cfg.name
                info.mkdir(parents=True)
                install = home / 'IDE.app' if system == 'Darwin' else home / 'IDE'
                binary = install / 'Contents/bin' if system == 'Darwin' else install / 'bin'
                binary.mkdir(parents=True)
                (binary / name).write_bytes(b'-Xmx2048m\n-Dkeep=yes\n')
                (info / '.home').write_text(str(install), encoding='utf-8')
                targets = self.jb.discover(system, home, {})
                self.assertEqual(len(targets), 1)
                self.assertEqual(targets[0].vm, cfg / name)
                self.assertEqual(targets[0].seed, b'-Xmx2048m\n-Dkeep=yes\n')

    def test_missing_defaults_are_not_replaced_by_three_line_file(self):
        self.vm.unlink()
        with self.assertRaises(ValueError):
            self.jb.make_target(self.config, 'Windows', 'idea', None, None, {})

    def test_environment_override_requires_explicit_effective_file(self):
        other = self.root / 'effective.vmoptions'
        other.write_bytes(b'-Xmx1g\n')
        env = {'IDEA_VM_OPTIONS': str(other)}
        with self.assertRaises(ValueError):
            self.jb.make_target(self.config, 'Windows', 'idea', None, None, env)
        target = self.jb.make_target(self.config, 'Windows', 'idea', None, other, env)
        self.assertEqual(target.vm, other)

    def test_merge_preserves_unrelated_options_and_is_idempotent(self):
        before = self.original + b'-javaagent:C:/old/ja-netfilter.jar\r\n'
        jar = self.root / 'space directory' / 'ja-netfilter.jar'
        after = self.jb.merge_options(before, jar)
        self.assertIn(b'-Xmx4096m\r\n', after)
        self.assertIn(b'-javaagent:C:/tools/monitor.jar\r\n', after)
        self.assertNotIn(b'C:/old/', after)
        self.assertEqual(after.count(b'ja-netfilter.jar'), 1)
        self.assertEqual(self.jb.merge_options(after, jar), after)

    def test_newline_or_equals_in_agent_path_is_rejected(self):
        for part in ['bad\noption', 'bad=option']:
            with self.subTest(part=part), self.assertRaises(ValueError):
                self.jb.merge_options(b'-Xmx1g\n', self.root / part / 'ja-netfilter.jar')

    def test_preview_is_read_only(self):
        plan = self.plan()
        self.assertTrue(plan)
        self.assertEqual(self.vm.read_bytes(), self.original)
        self.assertEqual(self.key.read_bytes(), b'original-license')
        self.assertFalse(self.state.exists())

    def test_install_repeat_and_restore_exact_original_bytes(self):
        plan = self.plan()
        backup = self.jb.apply_plan(plan, self.state)
        self.assertIn(b'ja-netfilter.jar', self.vm.read_bytes())
        self.assertNotEqual(self.key.read_bytes(), b'original-license')
        self.assertEqual(self.plan(), [])
        self.jb.restore(backup, self.state, apply=True)
        self.assertEqual(self.vm.read_bytes(), self.original)
        self.assertEqual(self.key.read_bytes(), b'original-license')

    def test_restore_does_not_overwrite_later_user_edits(self):
        backup = self.jb.apply_plan(self.plan(), self.state)
        modified = self.vm.read_bytes() + b'\n-Xmx8g\n'
        self.vm.write_bytes(modified)
        with self.assertRaises(ValueError):
            self.jb.restore(backup, self.state, apply=True)
        self.assertEqual(self.vm.read_bytes(), modified)

    def test_changed_file_between_preview_and_apply_is_not_overwritten(self):
        plan = self.plan()
        self.vm.write_bytes(b'new user contents')
        with self.assertRaises(ValueError):
            self.jb.apply_plan(plan, self.state)
        self.assertEqual(self.vm.read_bytes(), b'new user contents')

    def test_changed_file_after_discovery_is_not_overwritten(self):
        target = self.jb.make_target(self.config, 'Windows', 'idea', None, None, {})
        self.vm.write_bytes(b'edited after discovery')
        with self.assertRaises(ValueError):
            self.jb.make_plan([target], self.bundle, self.state)

    def test_new_file_after_discovery_is_not_overwritten(self):
        self.vm.unlink()
        defaults = self.root / 'IDE/bin' / self.vm.name
        defaults.parent.mkdir(parents=True)
        defaults.write_bytes(b'-Xmx2g\n')
        target = self.jb.make_target(self.config, 'Windows', 'idea', defaults.parent.parent, None, {})
        self.vm.write_bytes(b'-Xmx8g\n')
        with self.assertRaises(ValueError):
            self.jb.make_plan([target], self.bundle, self.state)
        self.assertEqual(self.vm.read_bytes(), b'-Xmx8g\n')

    def test_restore_keeps_payload_used_by_another_ide(self):
        first = self.jb.apply_plan(self.plan(), self.state)
        second = self.root / 'other' / 'PyCharm2026.2'
        second.mkdir(parents=True)
        vm = second / 'pycharm64.exe.vmoptions'
        vm.write_bytes(b'-Xmx2g\n')
        target = self.jb.make_target(second, 'Windows', 'pycharm', None, None, {})
        self.jb.apply_plan(self.jb.make_plan([target], self.bundle, self.state), self.state)
        self.jb.restore(first, self.state, apply=True)
        agent_line = next(line for line in vm.read_text().splitlines() if line.startswith('-javaagent:'))
        self.assertTrue(Path(agent_line[len('-javaagent:'):]).is_file())

    def test_restore_removes_new_vmoptions_and_keeps_defaults(self):
        self.vm.unlink()
        defaults = self.root / 'IDE' / 'bin' / self.vm.name
        defaults.parent.mkdir(parents=True)
        defaults.write_bytes(b'-Xmx3g\n-Dkeep=default\n')
        target = self.jb.make_target(self.config, 'Windows', 'idea', defaults.parent.parent, None, {})
        backup = self.jb.apply_plan(self.jb.make_plan([target], self.bundle, self.state), self.state)
        self.assertIn(b'-Dkeep=default\n', self.vm.read_bytes())
        self.jb.restore(backup, self.state, apply=True)
        self.assertFalse(self.vm.exists())
        self.assertEqual(defaults.read_bytes(), b'-Xmx3g\n-Dkeep=default\n')

    def test_write_failure_rolls_back_existing_files(self):
        plan = self.plan()
        original_write = self.jb.atomic_write
        failed = False

        def fail_once(path, data, mode=None):
            nonlocal failed
            if path == self.key and not failed:
                failed = True
                raise OSError('simulated disk failure')
            return original_write(path, data, mode)

        with patch.object(self.jb, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.jb.apply_plan(plan, self.state)
        self.assertEqual(self.vm.read_bytes(), self.original)
        self.assertEqual(self.key.read_bytes(), b'original-license')

    def test_restore_checks_backup_integrity_before_writing(self):
        backup = self.jb.apply_plan(self.plan(), self.state)
        folder = self.state / 'backups' / backup
        for file in folder.glob('*.bin'):
            file.write_bytes(b'corrupt')
        installed = self.vm.read_bytes()
        with self.assertRaises(ValueError):
            self.jb.restore(backup, self.state, apply=True)
        self.assertEqual(self.vm.read_bytes(), installed)

    def test_symlink_target_is_rejected(self):
        other = self.root / 'outside.vmoptions'
        other.write_bytes(b'outside')
        self.vm.unlink()
        try:
            self.vm.symlink_to(other)
        except OSError:
            self.skipTest('OS does not permit symlink creation')
        with self.assertRaises(ValueError):
            self.plan()
        self.assertEqual(other.read_bytes(), b'outside')


if __name__ == '__main__':
    unittest.main()
