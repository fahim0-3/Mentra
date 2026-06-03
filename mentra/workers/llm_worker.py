import time
import re
from PyQt5.QtCore import QObject, pyqtSignal as Signal

class StreamWorker(QObject):
    text_updated = Signal(str, str) # chat_id, text
    finished = Signal(str, str)     # chat_id, text
    error = Signal(str, str)        # chat_id, message

    def __init__(self, client, model, chat_id, messages, stop_evt):
        super().__init__()
        self.client = client
        self.model = model
        self.chat_id = chat_id
        self.messages = messages
        self.stop_evt = stop_evt

    def run(self):
        try:
            full = ""
            last_t = 0
            for chunk in self.client.chat(
                model=self.model,
                messages=self.messages,
                stream=True,
                options={"temperature": 0.3},
                keep_alive="15m",
            ):
                if self.stop_evt.is_set():
                    break
                full += chunk["message"]["content"]
                now = time.time()
                if now - last_t > 0.15:
                    self.text_updated.emit(self.chat_id, full)
                    last_t = now
            
            def sanitize(text):
                if len(text.strip()) < 50 and "\n" not in text:
                    text = re.sub(r'^\*\*(.*)\*\*$', r'\1', text.strip())
                    text = re.sub(r'^__(.*)__$', r'\1', text.strip())
                    text = re.sub(r'^`(.*)`$', r'\1', text.strip())
                return text
            
            self.text_updated.emit(self.chat_id, sanitize(full))
            self.finished.emit(self.chat_id, sanitize(full))
        except Exception as e:
            msg = str(e)
            if "10061" in msg or "Connection refused" in msg or "ConnectionError" in msg:
                 msg = "Ollama is not running. Please start Ollama to use the assistant."
            elif "model" in msg and "not found" in msg:
                 msg = f"Model '{self.model}' not found. Please pull it using 'ollama pull {self.model}'."
            self.error.emit(self.chat_id, msg)
