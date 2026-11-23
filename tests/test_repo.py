"""What has to hold across the repo: every module imports, one version, the add-on's YAML, and the texts."""
import glob
import importlib
import json
import os
import re
import string
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "frame_art")
PACKAGE = os.path.join(ADDON, "frameart")
YAML_FILES = ["config.yaml"] + sorted(os.path.relpath(p, ADDON)
                                      for p in glob.glob(os.path.join(ADDON, "translations", "*.yaml")))


def read(*path):
    with open(os.path.join(*path), encoding="utf-8") as f:
        return f.read()


def modules():
    return sorted(os.path.splitext(n)[0] for n in os.listdir(PACKAGE) if n.endswith(".py"))


def parsed():
    """The YAML files as JSON, parsed by scripts/check.sh on the Mac (Python here has no YAML parser)."""
    path = os.environ.get("FRAMEART_YAML")
    if not path:
        raise unittest.SkipTest("YAML not parsed here; scripts/check.sh parses it")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def tr_keys(page):
    """The keys in the page's tr() calls: every string in the first argument, but not one compared or added to."""
    keys = set()
    for m in re.finditer(r"\btr\(", page):
        i, depth = m.end(), 0
        while True:  # to the end of the first argument
            c = page[i]
            if c in "\"'":  # past the string, and any escaped quote in it
                i += 1
                while page[i] != c:
                    i += 2 if page[i] == "\\" else 1
                i += 1
                continue
            if c in "([{":
                depth += 1
            elif c in ")]}" and depth:
                depth -= 1
            elif c in ",)]}":
                break
            i += 1
        arg = page[m.end():i]
        for s in re.finditer(r'"([^"]*)"|\'([^\']*)\'', arg):
            before, after = arg[:s.start()].rstrip(), arg[s.end():].lstrip()
            if not before.endswith(("+", "==", "!=")) and not after.startswith(("+", "==", "!=")):
                keys.add(s.group(1) if s.group(1) is not None else s.group(2))
    return keys


class ModulesTest(unittest.TestCase):
    def test_every_module_imports(self):
        for name in modules():
            with self.subTest(module=name):
                if name == "__main__":  # it runs main() when imported
                    compile(read(PACKAGE, "__main__.py"), "__main__.py", "exec")
                else:
                    importlib.import_module("frameart" if name == "__init__" else "frameart." + name)

    def test_main_runs(self):
        got = subprocess.run([sys.executable, "-m", "frameart", "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(got.returncode, 0, got.stderr[-2000:])


class VersionTest(unittest.TestCase):
    def test_config_yaml_and_package_agree(self):
        from frameart import __version__
        found = re.findall(r'^version:\s*"?([^"\s]+)"?\s*$', read(ADDON, "config.yaml"), re.M)
        self.assertEqual(found, [__version__], "version in config.yaml and frameart/__init__.py")


class YamlTest(unittest.TestCase):
    def test_no_tabs(self):
        for name in YAML_FILES:
            with self.subTest(file=name):
                lines = [n for n, line in enumerate(read(ADDON, name).splitlines(), 1) if "\t" in line]
                self.assertEqual(lines, [], "tabs on these lines")

    def test_parsed_files_are_all_here(self):
        self.assertEqual(sorted(parsed()), sorted(YAML_FILES))

    def test_config(self):
        cfg = parsed()["config.yaml"]
        for key in ("name", "version", "slug", "description", "arch", "options", "schema"):
            self.assertIn(key, set(cfg))
        from frameart import __version__
        self.assertEqual(cfg["version"], __version__)
        self.assertEqual(set(cfg["options"]) - set(cfg["schema"]), set(), "options without a schema")
        services = {s["name"] for s in cfg["options"]["services"]}
        for src in cfg["options"]["sources"]:
            with self.subTest(source=src.get("name")):
                self.assertIn(src["type"], services | {"folder", "json"})

    def test_translations(self):
        cfg = parsed()["config.yaml"]
        for name, tr in parsed().items():
            if not name.startswith("translations/"):
                continue
            with self.subTest(file=name):
                self.assertEqual(set(tr["configuration"]), set(cfg["schema"]), "options and their translations")
                for key, text in tr["configuration"].items():
                    self.assertTrue(text.get("name"), key)
                self.assertEqual(set(tr.get("network") or {}), set(cfg.get("ports") or {}))


class TextsTest(unittest.TestCase):
    """i18n.t() falls back to English, and the page's tr() to the key itself."""

    @classmethod
    def setUpClass(cls):
        from frameart import i18n
        cls.i18n = i18n

    def test_norwegian_matches_english(self):
        en, nb = self.i18n.STRINGS["en"], self.i18n.STRINGS["nb"]
        fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}
        self.assertEqual(set(nb) - set(en), set(), "only in nb: t() reads English first")
        for key, text in nb.items():
            with self.subTest(key=key):
                self.assertIs(type(text), type(en[key]))
                if isinstance(text, str):
                    self.assertEqual(fields(text), fields(en[key]))
                elif isinstance(text, list):
                    self.assertEqual(len(text), len(en[key]))
                else:
                    self.assertEqual(set(text), set(en[key]))

    def test_keys_used_in_python(self):
        from frameart import service
        used = set(service.SAVER.values())
        for name in modules():
            used |= set(re.findall(r'\bt\("(\w+)"', read(PACKAGE, name + ".py")))
        self.assertEqual(used - set(self.i18n.STRINGS["en"]), set())

    def test_keys_used_on_the_page(self):
        page = read(PACKAGE, "page.html")
        used = tr_keys(page) | set(re.findall(r'data-t="(\w+)"', page))
        self.assertEqual(used - set(self.i18n.PAGE), set())


if __name__ == "__main__":
    unittest.main()
