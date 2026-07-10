"""
app.py
Desktop GUI for ClonerCC — scrape + download TikTok videos.
Run with: python app.py
"""

import queue
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

# ── Theme ────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ── Redirect stdout/stderr to a queue so the GUI can show logs ───────────────
class QueueWriter:
    """Captures print() output and puts it in a queue for the GUI to consume."""

    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str):
        if text.strip():
            self._q.put(text.rstrip())

    def flush(self):
        pass


LOGO_PATH = Path("assets/IMG_0464.PNG")

# ── Main window ───────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ClonerCC")
        self.geometry("720x620")
        self.resizable(False, False)

        # Window icon
        if LOGO_PATH.exists():
            icon = ctk.CTkImage(
                light_image=Image.open(LOGO_PATH),
                dark_image=Image.open(LOGO_PATH),
                size=(32, 32),
            )
            # Use a label trick to set the taskbar icon
            try:
                pil_icon = Image.open(LOGO_PATH).resize((32, 32))
                import tempfile, os
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                pil_icon.save(tmp.name)
                tmp.close()
                self.iconphoto(True, __import__("tkinter").PhotoImage(file=tmp.name))
                os.unlink(tmp.name)
            except Exception:
                pass

        self._log_queue: queue.Queue = queue.Queue()
        self._running = False

        self._build_ui()
        self._poll_logs()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        pad = {"padx": 20, "pady": 6}

        # ── Logo + Title ──────────────────────────────────────────────────────
        if LOGO_PATH.exists():
            logo_img = ctk.CTkImage(
                light_image=Image.open(LOGO_PATH),
                dark_image=Image.open(LOGO_PATH),
                size=(88, 88),
            )
            ctk.CTkLabel(self, image=logo_img, text="").pack(pady=(20, 4))

        ctk.CTkLabel(
            self, text="ClonerCC", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=(4, 2))
        ctk.CTkLabel(
            self, text="TikTok scraper & downloader",
            text_color="gray60", font=ctk.CTkFont(size=12)
        ).pack(pady=(0, 16))

        # ── Form frame ────────────────────────────────────────────────────────
        form = ctk.CTkFrame(self, corner_radius=12)
        form.pack(fill="x", **pad)

        # Username
        self._add_label(form, "@usuario")
        self.username_var = ctk.StringVar()
        ctk.CTkEntry(
            form, textvariable=self.username_var,
            placeholder_text="ex: dakpsico1",
            height=36,
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Max videos
        self._add_label(form, "Máximo de vídeos  (deixe 0 para todos)")
        self.max_var = ctk.StringVar(value="10")
        ctk.CTkEntry(
            form, textvariable=self.max_var,
            placeholder_text="10",
            height=36,
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Cookies file
        self._add_label(form, "Arquivo de cookies (.json)")
        cookies_row = ctk.CTkFrame(form, fg_color="transparent")
        cookies_row.pack(fill="x", padx=16, pady=(0, 10))
        self.cookies_var = ctk.StringVar(value=str(Path("my_cookies.json").resolve()))
        ctk.CTkEntry(
            cookies_row, textvariable=self.cookies_var, height=36
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            cookies_row, text="Escolher", width=90, height=36,
            command=self._pick_cookies
        ).pack(side="left")

        # Output directory
        self._add_label(form, "Pasta de destino")
        output_row = ctk.CTkFrame(form, fg_color="transparent")
        output_row.pack(fill="x", padx=16, pady=(0, 16))
        self.output_var = ctk.StringVar(value=str(Path("downloads").resolve()))
        ctk.CTkEntry(
            output_row, textvariable=self.output_var, height=36
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            output_row, text="Escolher", width=90, height=36,
            command=self._pick_output
        ).pack(side="left")

        # ── Action button ─────────────────────────────────────────────────────
        self.run_btn = ctk.CTkButton(
            self, text="▶  Scrape + Download",
            height=44, font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start,
        )
        self.run_btn.pack(fill="x", padx=20, pady=(10, 6))

        # ── Log box ───────────────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Log", anchor="w").pack(fill="x", padx=20)
        self.log_box = ctk.CTkTextbox(
            self, height=180, font=ctk.CTkFont(family="Consolas", size=12),
            wrap="none",
        )
        self.log_box.pack(fill="both", expand=True, padx=20, pady=(4, 20))
        self.log_box.configure(state="disabled")

    def _add_label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text, anchor="w",
            font=ctk.CTkFont(size=12), text_color="gray80"
        ).pack(fill="x", padx=16, pady=(10, 2))

    # ── File / folder pickers ─────────────────────────────────────────────────
    def _pick_cookies(self):
        path = filedialog.askopenfilename(
            title="Selecionar arquivo de cookies",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
        )
        if path:
            self.cookies_var.set(path)

    def _pick_output(self):
        path = filedialog.askdirectory(title="Selecionar pasta de destino")
        if path:
            self.output_var.set(path)

    # ── Log helpers ───────────────────────────────────────────────────────────
    def _append_log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_logs(self):
        """Drain the log queue and write to the textbox (runs on main thread)."""
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    # ── Validation ────────────────────────────────────────────────────────────
    def _validate(self) -> bool:
        if not self.username_var.get().strip():
            self._append_log("✖ Preencha o campo @usuario.")
            return False
        if not Path(self.cookies_var.get()).exists():
            self._append_log("✖ Arquivo de cookies não encontrado.")
            return False
        max_val = self.max_var.get().strip()
        if max_val and not max_val.isdigit():
            self._append_log("✖ Máximo de vídeos deve ser um número.")
            return False
        return True

    # ── Run in background thread ──────────────────────────────────────────────
    def _start(self):
        if self._running:
            return
        if not self._validate():
            return

        self._running = True
        self.run_btn.configure(state="disabled", text="⏳  Processando...")
        self._append_log("─" * 60)

        thread = threading.Thread(target=self._worker, daemon=True)
        thread.start()

    def _worker(self):
        # Redirect stdout so scraper/downloader logs appear in the GUI
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        writer = QueueWriter(self._log_queue)
        sys.stdout = writer
        sys.stderr = writer

        try:
            from scraper import scrape_profile
            from downloader import download_videos

            username  = self.username_var.get().strip()
            cookies   = self.cookies_var.get().strip()
            output    = self.output_var.get().strip()
            max_str   = self.max_var.get().strip()
            max_videos = int(max_str) if max_str and int(max_str) > 0 else None

            urls = scrape_profile(username, cookies_path=cookies, max_videos=max_videos)

            if urls:
                download_videos(urls, output)
                self._log_queue.put(f"\n✔ Concluído! {len(urls)} vídeo(s) em: {output}")
            else:
                self._log_queue.put("✖ Nenhuma URL encontrada.")

        except Exception as e:
            self._log_queue.put(f"✖ Erro: {e}")

        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            self.after(0, self._on_done)

    def _on_done(self):
        self._running = False
        self.run_btn.configure(state="normal", text="▶  Scrape + Download")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
