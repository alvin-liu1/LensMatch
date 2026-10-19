"""Exercise real desktop callbacks where Tk is available (Windows CI)."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
try:
    import tkinter as tk
    from tkinter import ttk
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False


@unittest.skipUnless(TK_AVAILABLE, 'Tk runtime unavailable on this host')
class DesktopTests(unittest.TestCase):
    def test_settings_and_background_match(self):
        from matching.gui import launch
        from matching.models import Config
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        errors, preferences = [], []
        root.report_callback_exception = lambda *args: errors.append(str(args))
        started = time.monotonic()
        def widgets(parent):
            return [child for direct in parent.winfo_children() for child in [direct, *widgets(direct)]]
        def button(text, parent=root):
            return next(w for w in widgets(parent) if isinstance(w, ttk.Button) and w.cget('text') == text)
        def setup():
            try:
                button('阈值与权重…').invoke()
                dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
                field = next(w for w in dialog.winfo_children() if isinstance(w, ttk.Entry) and w.grid_info()['row'] == 2 and w.grid_info()['column'] == 1)
                field.delete(0, 'end')
                field.insert(0, '2')
                button('应用', dialog).invoke()
                button('开始匹配').invoke()
                root.after(50, check)
            except Exception as exc:
                errors.append(str(exc))
                root.destroy()
        def check():
            try:
                if str(button('打开结果目录').cget('state')) == 'normal':
                    root.destroy()
                elif time.monotonic() - started > 15:
                    errors.append('Background matching timed out')
                    root.destroy()
                else:
                    root.after(50, check)
            except Exception as exc:
                errors.append(str(exc))
                root.destroy()
        with tempfile.TemporaryDirectory() as tmp:
            root.after(100, setup)
            with patch('matching.gui.tk.Tk', return_value=root), patch('matching.gui.read_preferences', return_value={}), patch('matching.gui.save_preferences', side_effect=lambda data: preferences.append(data)), patch('matching.gui.messagebox.showerror', side_effect=lambda title, detail, **kw: errors.append(detail)):
                launch(Config(), input_path=str(Path(__file__).resolve().parents[1] / 'examples/noimu'), output=tmp)
            self.assertFalse(errors)
            self.assertTrue(preferences)
            self.assertEqual(preferences[0]['config']['aec_limit'], 2)
            summaries = list(Path(tmp).glob('*/summary.json'))
            self.assertEqual(len(summaries), 1)
            self.assertEqual(json.loads(summaries[0].read_text(encoding='utf-8'))['配对数'], 5)
