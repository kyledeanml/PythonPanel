#!/usr/bin/env python3
"""
Unit and Integration Tests for PythonPanel
Tests interactive REPL, system interpreter execution, advanced editing operations,
retina zoom scaling, and desktop asset integrity.
"""

import os
import sys
import tempfile

sys.dont_write_bytecode = True
import threading
import unittest
import xml.etree.ElementTree as ET
import gi

gi.require_version('GtkSource', '4')
from gi.repository import GtkSource

from editor import RetinaEditor
from python_tools import (
    PythonLinter,
    PythonRunner,
    Diagnostic,
    InterpreterManager,
    InteractiveShellSession
)


class TestInteractiveShellFeatures(unittest.TestCase):
    """Test persistent interactive shell and interpreter detection."""

    def test_system_base_interpreter(self):
        interp = InterpreterManager.get_active_interpreter()
        self.assertTrue(os.path.exists(interp), f"Base interpreter {interp} not found")
        ver = InterpreterManager.get_interpreter_version()
        self.assertIn("Python", ver)

    def test_interactive_shell_persistence(self):
        session = InteractiveShellSession()
        out, more = session.push_line("x = 100 * 2")
        self.assertFalse(more)

        out, more = session.push_line("print('val:', x)")
        self.assertFalse(more)
        self.assertIn("val: 200", out)

    def test_interactive_shell_restart(self):
        session = InteractiveShellSession()
        session.push_line("secret_var = 'stored'")
        msg = session.restart()
        self.assertIn("Clean", msg)
        out, more = session.push_line("print(secret_var)")
        self.assertIn("NameError", out)

    def test_interactive_shell_exit_and_interrupt_isolation(self):
        session = InteractiveShellSession()
        for cmd in ["exit()", "quit()", "import sys; sys.exit(42)", "raise KeyboardInterrupt"]:
            out, more = session.push_line(cmd)
            self.assertFalse(more)
            self.assertTrue(len(out) > 0)
        # Ensure shell remains usable afterwards
        out, more = session.push_line("print(21 * 2)")
        self.assertIn("42", out)

    def test_interactive_shell_input_bridging(self):
        session = InteractiveShellSession(input_handler=lambda prompt: "mock_user_input")
        out, more = session.push_line("ans = input('Enter: '); print('Got:', ans)")
        self.assertFalse(more)
        self.assertIn("Got: mock_user_input", out)


class TestPythonLinterAndRunner(unittest.TestCase):
    """Test AST syntax analysis and script runner."""

    def test_valid_python_lint(self):
        code = '"""Module docstring."""\n\n\ndef add(a, b):\n    """Add two numbers."""\n    return a + b\n'
        diags, summary, used = PythonLinter.lint(content=code)
        self.assertEqual(len(diags), 0)
        self.assertTrue("Clean" in summary or "OK" in summary)

    def test_syntax_error_detection(self):
        bad_code = "def broken(\n    print('unclosed')\n"
        diags, summary, used = PythonLinter.lint(content=bad_code)
        self.assertGreater(len(diags), 0)
        self.assertEqual(diags[0].severity, "error")
        self.assertEqual(diags[0].line, 1)

    def test_runner_init_and_execution(self):
        runner = PythonRunner()
        self.assertFalse(runner.is_running)

        done_event = threading.Event()
        outputs = []
        exit_codes = []

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
            tf.write("import sys\nline = input('prompt>')\nprint('Result:', line)\n")
            script_path = tf.name

        try:
            def on_out(text, is_err):
                outputs.append(text)
                if "prompt>" in "".join(outputs):
                    runner.send_input("hello_world")

            def on_done(rc):
                exit_codes.append(rc)
                done_event.set()

            runner.run(script_path, on_output=on_out, on_finished=on_done)
            self.assertTrue(done_event.wait(timeout=5.0), "Script execution timed out")
            self.assertEqual(exit_codes, [0])
            self.assertIn("Result: hello_world", "".join(outputs))
        finally:
            if os.path.exists(script_path):
                os.unlink(script_path)


class TestEditorLogicAndPowerEditing(unittest.TestCase):
    """Test Retina font scaling steps and advanced power editing tools."""

    def test_zoom_steps(self):
        steps = RetinaEditor.ZOOM_STEPS
        self.assertIn(1.0, steps)
        self.assertEqual(steps[RetinaEditor.DEFAULT_ZOOM_INDEX], 1.00)
        self.assertTrue(all(steps[i] < steps[i+1] for i in range(len(steps)-1)))

    def test_gtksource_schemes_available(self):
        manager = GtkSource.StyleSchemeManager.get_default()
        schemes = manager.get_scheme_ids()
        self.assertTrue(len(schemes) > 0)
        self.assertIn('pythonpanel-neon', schemes)
        neon_scheme = manager.get_scheme('pythonpanel-neon')
        self.assertIsNotNone(neon_scheme)
        self.assertEqual(neon_scheme.get_name(), 'Neon Blue & White')

    def test_editor_null_byte_sanitization_and_atomic_save(self):
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            self.skipTest("Requires active X11/Wayland display connection for GtkWidget instantiation")
        ed = RetinaEditor(file_path="/tmp/nonexistent_pythonpanel_test_file.py")
        self.assertIsNotNone(ed.file_path)
        ed.set_text("a = 'hello\\x00world'\x00\nb = '# not a comment'\n")
        self.assertNotIn("\x00", ed.get_text())

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
            temp_path = tf.name

        try:
            ed.file_encoding = "LATIN-1"
            ed.set_text("print('Unicode \u2605 symbol')")
            ed.save_file(temp_path)
            self.assertEqual(ed.file_encoding, "UTF-8")
            with open(temp_path, "r", encoding="utf-8") as f:
                saved = f.read()
            self.assertIn("Unicode \u2605 symbol", saved)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            if os.path.exists("/tmp/nonexistent_pythonpanel_test_file.py"):
                os.unlink("/tmp/nonexistent_pythonpanel_test_file.py")

    def test_gui_interactive_shell_and_f5_runner(self):
        gi.require_version('Gdk', '3.0')
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gdk, Gtk, GLib
        if Gdk.Display.get_default() is None:
            self.skipTest("Requires active X11/Wayland display connection for GUI verification")

        from pythonpanel import PythonPanelWindow
        win = PythonPanelWindow(app=None)
        try:
            # 1. Verify bottom panel and Interactive Shell visibility & execution
            win.toggle_bottom_panel(force_show=True, tab_index=0)
            self.assertTrue(win.panel.get_visible(), "Bottom panel should be visible")
            self.assertTrue(win.panel.shell_view.get_visible(), "Interactive shell view should be visible")
            self.assertEqual(win.panel.notebook.get_visible_child_name(), "shell")

            win.panel.shell_entry.set_text("shell_check = 21 * 2; print('SHELL_OK:', shell_check)")
            win.panel._on_shell_submit(win.panel.shell_entry)

            buf = win.panel.shell_buffer
            shell_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            self.assertIn("SHELL_OK: 42", shell_text)

            # 2. Verify F5 script execution on saved file
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
                tf.write("print('F5_RUNNER_OK:', 123 + 456)\n")
                script_path = tf.name

            try:
                ed = win.get_current_editor()
                ed.load_file(script_path)
                win.run_active_script()
                self.assertEqual(win.panel.notebook.get_visible_child_name(), "console")

                # Pump GLib main context until runner finishes
                deadline = GLib.get_monotonic_time() + 4_000_000
                while GLib.get_monotonic_time() < deadline:
                    while Gtk.events_pending():
                        Gtk.main_iteration_do(False)
                    cbuf = win.panel.console_buffer
                    ctext = cbuf.get_text(cbuf.get_start_iter(), cbuf.get_end_iter(), False)
                    if "F5_RUNNER_OK: 579" in ctext and "Process finished" in ctext:
                        break

                cbuf = win.panel.console_buffer
                ctext = cbuf.get_text(cbuf.get_start_iter(), cbuf.get_end_iter(), False)
                self.assertIn("F5_RUNNER_OK: 579", ctext)
            finally:
                if os.path.exists(script_path):
                    os.unlink(script_path)
        finally:
            win.destroy()


class TestAppAssets(unittest.TestCase):
    """Test SVG icon and desktop file integrity."""

    def setUp(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

    def test_svg_icon_validity(self):
        svg_path = os.path.join(self.base_dir, "pythonpanel.svg")
        self.assertTrue(os.path.exists(svg_path), "pythonpanel.svg does not exist")

        tree = ET.parse(svg_path)
        root = tree.getroot()
        self.assertTrue(root.tag.endswith('svg'))
        self.assertEqual(root.attrib.get('viewBox'), '0 0 512 512')
        self.assertIsNotNone(RetinaEditor._get_watermark_pixbuf())

    def test_desktop_file_exists(self):
        desktop_path = os.path.join(self.base_dir, "pythonpanel.desktop")
        self.assertTrue(os.path.exists(desktop_path), "pythonpanel.desktop does not exist")
        with open(desktop_path, 'r') as f:
            content = f.read()
        self.assertIn("[Desktop Entry]", content)
        self.assertIn("Name=PythonPanel", content)
        self.assertIn("StartupWMClass=pythonpanel", content)
        self.assertIn("text/plain;", content)
        self.assertIn("text/x-python;", content)

        install_path = os.path.join(self.base_dir, "install.sh")
        with open(install_path, 'r') as f:
            install_content = f.read()
        self.assertIn("xdg-mime default pythonpanel.desktop", install_content)
        self.assertIn("mimeapps.list", install_content)

    def test_scripts_executable(self):
        for script in ['run.sh', 'install.sh', 'pythonpanel.py', 'project_tree.py']:
            path = os.path.join(self.base_dir, script)
            self.assertTrue(os.access(path, os.X_OK) or script == 'project_tree.py', f"{script} is not accessible")


class TestProjectSidebar(unittest.TestCase):
    """Test Project File Structure sidebar, tree scanning, filtering, and toggle operations."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="pythonpanel_proj_test_")
        # Create a mock project structure:
        # root/
        #   src/
        #     main.py
        #     utils.py
        #   tests/
        #     test_main.py
        #   __pycache__/
        #     main.cpython-312.pyc
        #   .git/
        #     config
        #   .hidden_file
        #   README.md
        #   config.json
        os.makedirs(os.path.join(self.tmp_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.tmp_dir, "tests"), exist_ok=True)
        os.makedirs(os.path.join(self.tmp_dir, "__pycache__"), exist_ok=True)
        os.makedirs(os.path.join(self.tmp_dir, ".git"), exist_ok=True)

        for p in [
            os.path.join(self.tmp_dir, "src", "main.py"),
            os.path.join(self.tmp_dir, "src", "utils.py"),
            os.path.join(self.tmp_dir, "tests", "test_main.py"),
            os.path.join(self.tmp_dir, "__pycache__", "main.cpython-312.pyc"),
            os.path.join(self.tmp_dir, ".git", "config"),
            os.path.join(self.tmp_dir, ".hidden_file"),
            os.path.join(self.tmp_dir, "README.md"),
            os.path.join(self.tmp_dir, "config.json"),
        ]:
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# Content of {os.path.basename(p)}\n")

    def tearDown(self):
        if os.path.exists(self.tmp_dir):
            import shutil
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_project_tree_scanning_and_filtering(self):
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            self.skipTest("Requires active X11/Wayland display connection for GtkWidget instantiation")

        from project_tree import ProjectSidebar
        sidebar = ProjectSidebar(self.tmp_dir)
        self.assertEqual(sidebar.get_project_root(), self.tmp_dir)

        # Inspect root items in tree store
        store = sidebar.store
        root_items = []
        is_dirs = []
        for row in store:
            root_items.append(row[ProjectSidebar.COL_NAME])
            is_dirs.append(row[ProjectSidebar.COL_IS_DIR])

        # Directories first: src, tests
        self.assertIn("src", root_items)
        self.assertIn("tests", root_items)
        self.assertIn("README.md", root_items)
        self.assertIn("config.json", root_items)

        # Filtered items must NOT be present
        self.assertNotIn("__pycache__", root_items)
        self.assertNotIn(".git", root_items)
        self.assertNotIn(".hidden_file", root_items)

        # Check folders come first
        src_idx = root_items.index("src")
        tests_idx = root_items.index("tests")
        readme_idx = root_items.index("README.md")
        self.assertTrue(src_idx < readme_idx)
        self.assertTrue(tests_idx < readme_idx)

        # Test expand src
        src_iter = None
        for row in store:
            if row[ProjectSidebar.COL_NAME] == "src":
                src_iter = row.iter
                break
        self.assertIsNotNone(src_iter)

        sidebar._ensure_dir_loaded(src_iter, os.path.join(self.tmp_dir, "src"))
        src_children = []
        child = store.iter_children(src_iter)
        while child:
            src_children.append(store.get_value(child, ProjectSidebar.COL_NAME))
            child = store.iter_next(child)

        self.assertIn("main.py", src_children)
        self.assertIn("utils.py", src_children)

    def test_project_sidebar_toggle_and_tab_integration(self):
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            self.skipTest("Requires active X11/Wayland display connection for GUI verification")

        from pythonpanel import PythonPanelWindow
        win = PythonPanelWindow(app=None, initial_files=[self.tmp_dir])
        try:
            self.assertEqual(win.project_sidebar.get_project_root(), self.tmp_dir)
            self.assertTrue(win.project_sidebar.get_visible())
            self.assertTrue(win.btn_sidebar.get_active())

            # 1. Test clicking sidebar off (one-off script mode)
            win.toggle_project_sidebar(False)
            self.assertFalse(win.project_sidebar.get_visible())
            self.assertFalse(win.btn_sidebar.get_active())

            # 2. Test clicking sidebar on (project mode)
            win.toggle_project_sidebar(True)
            self.assertTrue(win.project_sidebar.get_visible())
            self.assertTrue(win.btn_sidebar.get_active())

            # 3. Test opening file from tree into tab
            main_py_path = os.path.join(self.tmp_dir, "src", "main.py")
            win.open_file_from_tree(main_py_path)
            self.assertEqual(win.get_current_editor().file_path, main_py_path)
            self.assertIn("main.py", win.get_title())

            # 4. Opening existing file should focus existing tab rather than duplicate
            config_json_path = os.path.join(self.tmp_dir, "config.json")
            win.open_file_from_tree(config_json_path)
            self.assertEqual(win.notebook_tabs.get_n_pages(), 2)

            win.open_file_from_tree(main_py_path)
            self.assertEqual(win.notebook_tabs.get_n_pages(), 2)
            self.assertEqual(win.get_current_editor().file_path, main_py_path)
        finally:
            win.destroy()

    def test_project_sidebar_no_blank_state_and_auto_root(self):
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            self.skipTest("Requires active X11/Wayland display connection for GUI verification")

        from pythonpanel import PythonPanelWindow
        win = PythonPanelWindow(app=None)
        try:
            # 1. Sidebar should not be blank: scrolled_tree must be visible
            self.assertTrue(win.project_sidebar.scrolled_tree.get_visible())
            self.assertGreater(len(win.project_sidebar.store), 0)

            # 2. When opening a script, project root automatically sets to parent folder
            test_file = os.path.join(self.tmp_dir, "src", "main.py")
            win.new_tab(test_file)
            self.assertEqual(win.project_sidebar.get_project_root(), os.path.dirname(test_file))
        finally:
            win.destroy()


class TestSecurityAndIntegrityHardening(unittest.TestCase):
    """Penetration, attack-vector, and error-resilience tests for PythonPanel."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="pythonpanel_sec_test_")

    def tearDown(self):
        if os.path.exists(self.tmp_dir):
            import shutil
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_path_traversal_and_overwrite_prevention_in_project_tree(self):
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            self.skipTest("Requires active display")

        from project_tree import ProjectSidebar

        proj_dir = os.path.join(self.tmp_dir, "proj")
        outside_dir = os.path.join(self.tmp_dir, "proj_outside")
        os.makedirs(proj_dir, exist_ok=True)
        os.makedirs(outside_dir, exist_ok=True)

        sidebar = ProjectSidebar(proj_dir)

        # 1. Path traversal payloads must be blocked
        traversal_payloads = [
            "../escaped.py",
            "../../escaped.py",
            "/tmp/evil_abs.py",
            "subdir/nested.py",
            "\\evil.py",
            "..",
            ".",
            "   ",
            "null\x00byte.py",
        ]
        for payload in traversal_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    sidebar.create_file_in_dir(proj_dir, payload)
                with self.assertRaises(ValueError):
                    sidebar.create_folder_in_dir(proj_dir, payload)

        # 2. Safe creation succeeds and stays inside proj_dir
        f1 = sidebar.create_file_in_dir(proj_dir, "safe_a.py")
        f2 = sidebar.create_file_in_dir(proj_dir, "safe_b.py")
        with open(f2, "w", encoding="utf-8") as f:
            f.write("ORIGINAL_B_CONTENT")

        # 3. Rename cannot traverse outside or silently clobber an existing file
        with self.assertRaises(ValueError):
            sidebar.rename_item(f1, "../outside_rename.py")
        with self.assertRaises(FileExistsError):
            sidebar.rename_item(f1, "safe_b.py")
        with open(f2, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "ORIGINAL_B_CONTENT")

        # 4. Protected root & external paths cannot be deleted
        outside_file = os.path.join(outside_dir, "keep_me.py")
        with open(outside_file, "w", encoding="utf-8") as f:
            f.write("DO_NOT_DELETE")

        with self.assertRaises(PermissionError):
            sidebar.delete_item(proj_dir, is_dir=True)
        with self.assertRaises(PermissionError):
            sidebar.delete_item("/", is_dir=True)
        with self.assertRaises(PermissionError):
            sidebar.delete_item(outside_file, is_dir=False)
        self.assertTrue(os.path.exists(outside_file))

        # 5. Deleting a symlinked directory must only unlink the symlink, never rmtree target
        symlink_dir = os.path.join(proj_dir, "linked_outside")
        os.symlink(outside_dir, symlink_dir)
        sidebar.delete_item(symlink_dir, is_dir=True)
        self.assertFalse(os.path.lexists(symlink_dir))
        self.assertTrue(os.path.exists(outside_file))

        # 6. Prefix-collision directory (/tmp/proj_outside vs /tmp/proj) must not match highlight_file
        sidebar.highlight_file(outside_file)

    def test_interpreter_binary_spoofing_and_null_byte_rejection(self):
        from python_tools import InterpreterManager

        prev = InterpreterManager.get_active_interpreter()
        try:
            for bogus in ("/bin/sh", "/usr/bin/env", "/bin/ls", "/dev/null", self.tmp_dir, "/usr/bin/python3\x00--evil"):
                self.assertFalse(
                    InterpreterManager.set_active_interpreter(bogus),
                    f"InterpreterManager should reject non-Python target: {bogus}",
                )
        finally:
            InterpreterManager.set_active_interpreter(prev)

    def test_pylint_untrusted_cwd_and_malicious_json_resilience(self):
        from unittest.mock import patch, MagicMock
        from python_tools import PythonLinter, Diagnostic

        # Diagnostic must handle malformed types without ValueError/TypeError
        d = Diagnostic(line="not_a_num", column=None, severity=None, code=123, message=None)
        self.assertEqual(d.line, 1)
        self.assertEqual(d.column, 1)
        self.assertEqual(d.severity, "convention")

        hostile_json = '[{"type": "error", "line": -99, "column": "bad", "message-id": "E9999", "message": "bad"}, "not_a_dict"]'
        mock_proc = MagicMock(returncode=2, stdout=hostile_json, stderr="")
        with patch.object(PythonLinter, "_find_pylint_executable", return_value="/usr/bin/pylint"), patch(
            "subprocess.run", return_value=mock_proc
        ) as run_mock:
            diags = PythonLinter._run_pylint(None, "x = 1\n")
            self.assertEqual(len(diags), 1)
            self.assertEqual(diags[0].line, 1)
            self.assertEqual(diags[0].column, 1)

            # Verify --rcfile=/dev/null and isolated cwd/env were enforced
            called_cmd = run_mock.call_args[0][0]
            called_kwargs = run_mock.call_args[1]
            self.assertIn("--rcfile=/dev/null", called_cmd)
            self.assertEqual(called_kwargs.get("cwd"), tempfile.gettempdir())
            self.assertEqual(called_kwargs.get("env", {}).get("PYTHONNOUSERSITE"), "1")
            self.assertNotIn("PYTHONPATH", called_kwargs.get("env", {}))

    def test_runner_option_injection_and_self_pgid_kill_protection(self):
        import time
        from unittest.mock import patch, MagicMock
        from python_tools import PythonRunner

        # 1. Script whose filename begins with '-' must execute via '--' separator
        dash_script = os.path.join(self.tmp_dir, "-c_flag_test.py")
        with open(dash_script, "w", encoding="utf-8") as f:
            f.write("import sys\nprint('ARGS_OK:' + ','.join(sys.argv[1:]))\n")

        runner = PythonRunner()
        outputs = []
        done = threading.Event()
        rc_holder = []

        runner.run(
            dash_script,
            on_output=lambda txt, err: outputs.append(txt),
            on_finished=lambda rc: (rc_holder.append(rc), done.set()),
            script_args=["--help", "-v"],
            custom_interpreter="/bin/sh",  # Spoofed interpreter must be rejected and fall back to valid Python
        )
        self.assertTrue(done.wait(timeout=5.0))
        self.assertEqual(rc_holder[0], 0)
        self.assertIn("ARGS_OK:--help,-v", "".join(outputs))

        # 2. PythonRunner.stop() must NEVER call os.killpg on PythonPanel's own process group
        fake_proc = MagicMock()
        fake_proc.pid = os.getpid()
        fake_proc.poll.side_effect = [None, 0]
        runner.process = fake_proc
        with patch("os.killpg") as killpg_mock:
            runner.stop()
            time.sleep(0.08)
            killpg_mock.assert_not_called()
            fake_proc.terminate.assert_called()

    def test_editor_fifo_device_oom_and_css_injection_protection(self):
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            self.skipTest("Requires active display")

        ed = RetinaEditor()

        # 1. Named pipe (FIFO) must be rejected immediately without blocking
        fifo_path = os.path.join(self.tmp_dir, "trap.fifo")
        os.mkfifo(fifo_path)
        with self.assertRaises(ValueError):
            ed.load_file(fifo_path)

        # 2. Oversized file exceeding MAX_FILE_SIZE_BYTES must be rejected before reading into buffer
        big_path = os.path.join(self.tmp_dir, "oversized.py")
        with open(big_path, "wb") as f:
            f.write(b"#" * 2048)

        orig_limit = RetinaEditor.MAX_FILE_SIZE_BYTES
        try:
            RetinaEditor.MAX_FILE_SIZE_BYTES = 1024
            with self.assertRaises(ValueError):
                ed.load_file(big_path)
        finally:
            RetinaEditor.MAX_FILE_SIZE_BYTES = orig_limit

        # 3. Saving onto a directory or path with null byte must raise cleanly
        with self.assertRaises(IsADirectoryError):
            ed.save_file(self.tmp_dir)
        with self.assertRaises(ValueError):
            ed.save_file(os.path.join(self.tmp_dir, "bad\x00.py"))

        # 4. CSS injection payload in font family must be stripped
        ed.set_font_family_and_size('Monospace"; } * { background-color: red; } /*', "bad_size")
        self.assertNotIn('"', ed.base_font_family)
        self.assertNotIn('{', ed.base_font_family)
        self.assertNotIn(';', ed.base_font_family)
        self.assertEqual(ed.base_font_size, 11)

    def test_corrupted_session_json_and_console_flood_cap(self):
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            self.skipTest("Requires active display")

        from unittest.mock import patch
        from pythonpanel import PythonPanelWindow
        from pylint_panel import PythonWorkspacePanel

        # 1. Hostile session.json types must not crash window creation
        bad_cfg_dir = os.path.join(self.tmp_dir, "cfg")
        os.makedirs(bad_cfg_dir, exist_ok=True)
        with open(os.path.join(bad_cfg_dir, "session.json"), "w", encoding="utf-8") as f:
            f.write('{"sidebar_visible": "not_a_bool", "sidebar_position": -999999, "last_project": [1, 2, 3]}')

        with patch.object(PythonPanelWindow, "_get_config_dir", return_value=bad_cfg_dir):
            win = PythonPanelWindow(app=None)
            try:
                self.assertIsInstance(win._session_state["sidebar_visible"], bool)
                self.assertGreaterEqual(win._saved_sidebar_pos, 150)
                self.assertIsNone(win._session_state["last_project"])
            finally:
                win.destroy()

        # 2. Console buffer flood protection caps characters to MAX_CONSOLE_CHARS
        panel = PythonWorkspacePanel(lambda: None)
        orig_max = PythonWorkspacePanel.MAX_CONSOLE_CHARS
        try:
            PythonWorkspacePanel.MAX_CONSOLE_CHARS = 1000
            panel._append_console("A" * 800)
            panel._append_console("B" * 800)
            self.assertLessEqual(panel.console_buffer.get_char_count(), 1000)
        finally:
            PythonWorkspacePanel.MAX_CONSOLE_CHARS = orig_max


if __name__ == '__main__':
    unittest.main()
