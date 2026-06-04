from PyQt5.QtCore import QObject, pyqtSignal as Signal

class ScreenReaderWorker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def run(self):
        com_initialized = False
        try:
            # COM must be initialized on this thread for uiautomation
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com_initialized = True
            except ImportError:
                pass  # pythoncom not available, try without it

            import uiautomation as auto
            import time
            import pyautogui
            import pyperclip

            # Wait for modifier keys to be fully released (critical for Ctrl+I hotkey)
            try:
                import keyboard as kb
                for _ in range(20):  # up to 2 seconds
                    if not any(kb.is_pressed(k) for k in ['ctrl', 'shift', 'alt']):
                        break
                    time.sleep(0.1)
            except Exception:
                time.sleep(0.5)  # Fallback: just wait

            auto.SetGlobalSearchTimeout(1.0)
            time.sleep(0.3)

            fg = auto.GetForegroundControl()
            if not fg:
                self.error.emit("Unable to find active window.")
                return

            title = fg.Name
            content = ""

            lower_name = title.lower() if title else ""
            lower_class = fg.ClassName.lower() if fg.ClassName else ""

            is_browser_or_editor = False
            if any(x in lower_class for x in ["chrome", "mozilla", "edge", "browser"]) or \
               any(x in lower_name for x in ["code", "browser", "editor", "leetcode", "studio", "notepad"]):
                is_browser_or_editor = True

            old_clip = ""
            try:
                old_clip = pyperclip.paste()
            except Exception:
                pass

            if is_browser_or_editor:
                # Ensure no modifier keys are pressed before sending hotkeys
                pyautogui.keyUp('ctrl')
                pyautogui.keyUp('shift')
                pyautogui.keyUp('alt')
                time.sleep(0.05)

                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.15)
                pyautogui.hotkey('ctrl', 'c')
                time.sleep(0.15)
                pyautogui.press('right')

                try:
                    content = pyperclip.paste()
                except Exception:
                    content = ""

                if content == old_clip:
                    content = ""

            if not content or len(content) < 50:
                focused = auto.GetFocusedControl()
                if focused:
                    if hasattr(focused, 'GetValuePattern'):
                        try:
                            content = focused.GetValuePattern().Value
                        except Exception:
                            pass
                    if not content and hasattr(focused, 'GetTextPattern'):
                        try:
                            content = focused.GetTextPattern().DocumentRange.GetText(-1)
                        except Exception:
                            pass
                    if not content and focused.Name:
                        content = focused.Name

                if not content:
                    try:
                        edit = fg.EditControl(searchDepth=3)
                        if edit.Exists(0.2, 0.2) and hasattr(edit, 'GetValuePattern'):
                            content = edit.GetValuePattern().Value
                    except Exception:
                        pass

                if not content:
                    try:
                        doc = fg.DocumentControl(searchDepth=3)
                        if doc.Exists(0.2, 0.2) and hasattr(doc, 'GetTextPattern'):
                            content = doc.GetTextPattern().DocumentRange.GetText(-1)
                    except Exception:
                        pass

            if content and content != old_clip:
                try:
                    pyperclip.copy(old_clip)
                except Exception:
                    pass

            if not title and not content:
                self.error.emit("Unable to read text from this window directly.")
                return

            prompt_text = (
                "You are an assistant reading the user's screen. Read ALL the visible content, then "
                "respond directly and helpfully. Do NOT describe the screen.\n"
                "1) ONLY if this is clearly a CODING task (a code editor, programming problem, or a "
                "class/function template such as LeetCode's 'class Solution'): reply with ONLY the "
                "complete, runnable solution that EXACTLY matches the visible signature — same class and "
                "method names, parameter names, type hints, 'self', and indentation — ready to paste and "
                "submit, no explanation.\n"
                "2) OTHERWISE (an email, document, article, message, data, or any general question): "
                "reply in clear plain language — answer the question if one is asked, or concisely "
                "summarize the key details and important points. Do NOT write any code unless the task is "
                "genuinely about programming.\n"
                "If there is truly not enough readable content, reply ONLY with: 'The visible task is unclear.'\n\n"
            )
            if title:
                prompt_text += f"-- WINDOW TITLE --\n{title}\n\n"
            if content:
                if len(content) > 40000:
                    content = content[:40000] + "\n...[truncated]"
                prompt_text += f"-- CONTENT --\n{content}\n"

            self.finished.emit(prompt_text)

        except ImportError as e:
            self.error.emit(f"Missing library: {e}. Install 'uiautomation', 'pyperclip', and 'pywin32'.")
        except Exception as e:
            self.error.emit(f"Unable to read text from this window: {e}")
        finally:
            if com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
