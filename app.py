"""
app.py
Desktop GUI for ClonerCC — scrape + download TikTok videos.
Run with: python app.py
"""

import queue
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk

import customtkinter as ctk
from PIL import Image

# ── Theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

LOGO_PATH = Path("assets/IMG_0464.PNG")

STATUS_COLORS = {
    "pending"   : "#e0a800",
    "downloaded": "#28a745",
    "error"     : "#dc3545",
    "cleared"   : "#3a9bdc",
}


# ── Stdout redirect ───────────────────────────────────────────────────────────
class QueueWriter:
    def __init__(self, q: queue.Queue):
        self._q = q
        self._lock = threading.Lock()

    def write(self, text: str):
        if text.strip():
            with self._lock:
                self._q.put(text.rstrip())

    def flush(self):
        pass


# ── Main window ───────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ClonerCC")
        self.geometry("820x740")
        self.minsize(700, 600)
        self.resizable(True, True)

        # Window icon
        if LOGO_PATH.exists():
            try:
                pil_icon = Image.open(LOGO_PATH).resize((32, 32))
                import tempfile, os
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                pil_icon.save(tmp.name)
                tmp.close()
                self.iconphoto(True, tk.PhotoImage(file=tmp.name))
                os.unlink(tmp.name)
            except Exception:
                pass

        # Root grid: row 0 = header (fixed), row 1 = tabs (expands)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._log_queue: queue.Queue = queue.Queue()
        self._running = False
        self._settings = self._load_settings()

        self._build_header()
        self._build_tabs()
        self._poll_logs()

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        hdr.columnconfigure(0, weight=1)

        if LOGO_PATH.exists():
            logo_img = ctk.CTkImage(
                light_image=Image.open(LOGO_PATH),
                dark_image=Image.open(LOGO_PATH),
                size=(64, 64),
            )
            ctk.CTkLabel(hdr, image=logo_img, text="").pack()

        ctk.CTkLabel(hdr, text="ClonerCC",
                     font=ctk.CTkFont(size=22, weight="bold")).pack()
        ctk.CTkLabel(hdr, text="TikTok scraper & downloader",
                     text_color="gray60", font=ctk.CTkFont(size=12)).pack(pady=(0, 8))

    # ── Tabs ──────────────────────────────────────────────────────────────────
    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        self.tabs.add("⬇  Clonar")
        self.tabs.add("🗄  Banco de Dados")

        self._build_clone_tab(self.tabs.tab("⬇  Clonar"))
        self._build_db_tab(self.tabs.tab("🗄  Banco de Dados"))

    # =========================================================================
    # TAB 1 — Clonar
    # =========================================================================
    def _build_clone_tab(self, parent):
        # parent grid: row0=form(fixed) row1=btns(fixed) row2=qty(fixed) row3=log(expands)
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(2, weight=0)
        parent.grid_rowconfigure(3, weight=0)
        parent.grid_rowconfigure(4, weight=1)   # log expands
        parent.grid_columnconfigure(0, weight=1)

        # ── Form ──────────────────────────────────────────────────────────────
        form = ctk.CTkFrame(parent, corner_radius=10)
        form.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 6))
        form.columnconfigure(0, weight=1)

        self._lbl(form, "@usuario")
        self.username_var = ctk.StringVar()
        username_history = self._settings.get("username_history", [])
        self.username_combo = ctk.CTkComboBox(
            form,
            variable=self.username_var,
            values=username_history,
            height=34,
        )
        self.username_combo.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        if username_history:
            self.username_var.set(username_history[0])

        self._lbl(form, "Arquivo de cookies (.json)", row=2)
        crow = ctk.CTkFrame(form, fg_color="transparent")
        crow.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 8))
        crow.columnconfigure(0, weight=1)
        self.cookies_var = ctk.StringVar(value=str(Path("my_cookies.json").resolve()))
        ctk.CTkEntry(crow, textvariable=self.cookies_var, height=34
                     ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(crow, text="Escolher", width=86, height=34,
                      command=self._pick_cookies).grid(row=0, column=1)

        self._lbl(form, "Pasta de destino", row=4)
        orow = ctk.CTkFrame(form, fg_color="transparent")
        orow.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 14))
        orow.columnconfigure(0, weight=1)
        self.output_var = ctk.StringVar(value=str(Path("downloads").resolve()))
        ctk.CTkEntry(orow, textvariable=self.output_var, height=34
                     ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(orow, text="Escolher", width=86, height=34,
                      command=self._pick_output).grid(row=0, column=1)
        ctk.CTkButton(orow, text="🗑", width=34, height=34,
                      fg_color="#7a1a1a", hover_color="#5e1414",
                      command=self._clear_output).grid(row=0, column=2, padx=(6, 0))

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 2))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)

        self.scrape_btn = ctk.CTkButton(
            btn_row, text="🔍  Coletar tudo",
            height=42, font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2b5ea7", hover_color="#1e4080",
            command=self._start_scrape,
        )
        self.scrape_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.download_btn = ctk.CTkButton(
            btn_row, text="⬇  Baixar",
            height=42, font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1a7a3c", hover_color="#145e2e",
            command=self._start_download,
        )
        self.download_btn.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        # ── Qty row ───────────────────────────────────────────────────────────
        qty_row = ctk.CTkFrame(parent, fg_color="transparent")
        qty_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 6))
        qty_row.columnconfigure(0, weight=1)
        ctk.CTkLabel(qty_row, text="Qtd. para baixar:",
                     font=ctk.CTkFont(size=12), text_color="gray60"
                     ).pack(side="left", padx=(0, 6))
        self.qty_var = ctk.StringVar(value="10")
        ctk.CTkEntry(qty_row, textvariable=self.qty_var,
                     width=64, height=28).pack(side="left")
        ctk.CTkLabel(qty_row, text="  (0 = todos os pendentes)",
                     font=ctk.CTkFont(size=11), text_color="gray50"
                     ).pack(side="left")

        # Botão de limpeza de metadados — sempre visível
        self.clean_meta_btn = ctk.CTkButton(
            qty_row,
            text="🍎 Limpar Metadados",
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#5a2d82", hover_color="#3e1f5c",
            command=self._start_clean_metadata,
        )
        self.clean_meta_btn.pack(side="right", padx=(12, 0))

        # ── Log label + clear button ──────────────────────────────────────────
        log_hdr = ctk.CTkFrame(parent, fg_color="transparent")
        log_hdr.grid(row=3, column=0, sticky="ew", padx=14, pady=(4, 0))
        ctk.CTkLabel(log_hdr, text="Log", anchor="w").pack(side="left")
        ctk.CTkButton(
            log_hdr, text="🗑 Limpar", width=72, height=22,
            font=ctk.CTkFont(size=11),
            fg_color="#3a3a3a", hover_color="#555555",
            command=self._clear_log,
        ).pack(side="right")

        # ── Log box (expands) ─────────────────────────────────────────────────
        self.log_box = ctk.CTkTextbox(
            parent, font=ctk.CTkFont(family="Consolas", size=11), wrap="none",
        )
        self.log_box.grid(row=4, column=0, sticky="nsew", padx=14, pady=(2, 10))
        self.log_box.configure(state="disabled")

    # =========================================================================
    # TAB 2 — Banco de Dados
    # =========================================================================
    def _build_db_tab(self, parent):
        # row0=filters row1=stats row2=table(expands) row3=actions
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=0)
        parent.grid_rowconfigure(2, weight=1)   # table expands
        parent.grid_rowconfigure(3, weight=0)
        parent.grid_columnconfigure(0, weight=1)

        # ── Filter bar ────────────────────────────────────────────────────────
        filter_row = ctk.CTkFrame(parent, fg_color="transparent")
        filter_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))

        ctk.CTkLabel(filter_row, text="Filtrar @usuario:",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        self.filter_var = ctk.StringVar()
        ctk.CTkEntry(filter_row, textvariable=self.filter_var,
                     placeholder_text="deixe vazio para todos",
                     width=180, height=30).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(filter_row, text="Status:",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(6, 4))
        self.status_filter_var = ctk.StringVar(value="todos")
        ctk.CTkOptionMenu(filter_row,
                          values=["todos", "pending", "downloaded", "error", "cleared"],
                          variable=self.status_filter_var,
                          width=120, height=30).pack(side="left", padx=(0, 6))
        ctk.CTkButton(filter_row, text="🔄 Listar",
                      width=80, height=30,
                      command=self._refresh_table).pack(side="left")

        # ── Stats bar ─────────────────────────────────────────────────────────
        self.stats_label = ctk.CTkLabel(
            parent, text="", font=ctk.CTkFont(size=11), text_color="gray60", anchor="w"
        )
        self.stats_label.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))

        # ── Table ─────────────────────────────────────────────────────────────
        table_outer = ctk.CTkFrame(parent, corner_radius=8)
        table_outer.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 4))
        table_outer.grid_rowconfigure(0, weight=0)   # header
        table_outer.grid_rowconfigure(1, weight=1)   # scrollable rows
        table_outer.grid_columnconfigure(0, weight=1)

        # Header
        self._hdr_frame = tk.Frame(table_outer, bg="#1a1a2e")
        self._hdr_frame.grid(row=0, column=0, sticky="ew")
        self._build_table_header(self._hdr_frame)

        # Scrollable body
        self._scroll_frame = ctk.CTkScrollableFrame(table_outer)
        self._scroll_frame.grid(row=1, column=0, sticky="nsew")
        self._table_inner = self._scroll_frame
        self._row_frames: list[tk.Frame] = []
        self._selected_url: str | None = None

        # Reflow header widths when table resizes
        table_outer.bind("<Configure>", self._on_table_resize)

        # ── Action buttons ────────────────────────────────────────────────────
        act_row = ctk.CTkFrame(parent, fg_color="transparent")
        act_row.grid(row=3, column=0, sticky="ew", padx=14, pady=(2, 10))

        for text, color, hover, cmd, w in [
            ("🗑  Apagar selecionado", "#7a1a1a", "#5e1414", self._delete_selected, 170),
            ("🗑  Apagar perfil",      "#7a3a1a", "#5e2e14", self._delete_profile,  140),
            ("💣  Apagar tudo",        "#5a0a0a", "#440808", self._delete_all,       120),
            ("🔁  Resetar erros",      "#2b4a7a", "#1e3860", self._reset_errors,     130),
            ("🔍  Re-buscar descrições","#2b4a2a", "#1e3820", self._refetch_descriptions, 170),
        ]:
            ctk.CTkButton(act_row, text=text, width=w, height=34,
                          fg_color=color, hover_color=hover,
                          command=cmd).pack(side="left", padx=(0, 6))

        self._refresh_table()

    # ── Table header ──────────────────────────────────────────────────────────
    # Column definitions: (label, min_px, flex_weight)
    # flex_weight > 0 means the column shares extra space proportionally
    COL_DEFS = [
        ("🔗",          28,  0),
        ("#",           36,  0),
        ("Perfil",      80,  0),
        ("Status",      80,  0),
        ("ID do Vídeo", 150, 0),
        ("Descrição",   160, 1),   # ← this one absorbs all extra width
    ]

    def _build_table_header(self, parent: tk.Frame):
        for col, (label, min_w, _) in enumerate(self.COL_DEFS):
            tk.Label(parent, text=label, bg="#1a1a2e", fg="#aaaacc",
                     font=("Consolas", 10, "bold"),
                     anchor="w", padx=4).grid(row=0, column=col, sticky="ew")
            parent.columnconfigure(col, minsize=min_w,
                                   weight=self.COL_DEFS[col][2])

    def _on_table_resize(self, event):
        """Reapply column weights when the outer frame changes size."""
        self._build_table_header(self._hdr_frame)

    # ── Table rows ────────────────────────────────────────────────────────────
    def _refresh_table(self):
        from db import get_db

        db      = get_db()
        profile = self.filter_var.get().strip().lstrip("@") or None
        status  = self.status_filter_var.get()

        records = db.get_all(profile=profile)
        if status != "todos":
            records = [r for r in records if r.status == status]

        s     = db.stats(profile=profile)
        total = sum(s.values())
        self.stats_label.configure(
            text=f"Total: {total}  |  ⏳ pendentes: {s.get('pending', 0)}  "
                 f"✔ baixados: {s.get('downloaded', 0)}  ✖ erros: {s.get('error', 0)}"
        )

        for f in self._row_frames:
            f.destroy()
        self._row_frames.clear()
        self._selected_url = None

        for i, r in enumerate(records):
            bg    = "#1e1e2e" if i % 2 == 0 else "#16162a"
            color = STATUS_COLORS.get(r.status, "white")
            desc  = (r.description[:80] + "…") if len(r.description) > 80 else r.description
            url   = r.url

            row_f = tk.Frame(self._table_inner, bg=bg, cursor="hand2")
            row_f.pack(fill="x", pady=1)

            # Configure same column weights as header so content aligns
            for col, (_, min_w, flex) in enumerate(self.COL_DEFS):
                row_f.columnconfigure(col, minsize=min_w, weight=flex)

            # 🔗 clipboard button
            clip = tk.Label(row_f, text="🔗", bg=bg,
                            font=("Consolas", 10), cursor="hand2",
                            anchor="center", padx=4)
            clip.grid(row=0, column=0, sticky="ew")
            clip.bind("<Button-1>", lambda e, u=url: self._copy_to_clipboard(u))
            clip.bind("<Enter>",    lambda e, b=clip: b.configure(fg="#66aaff"))
            clip.bind("<Leave>",    lambda e, b=clip: b.configure(fg="#dddddd"))

            # Data columns
            for col, (val, fg_col) in enumerate([
                (str(i + 1),  "#dddddd"),
                (r.profile,   "#dddddd"),
                (r.status,    color),
                (r.video_id,  "#dddddd"),
                (desc or "—", "#dddddd"),
            ], start=1):
                tk.Label(row_f, text=val, bg=bg, fg=fg_col,
                         font=("Consolas", 10),
                         anchor="w", padx=4).grid(row=0, column=col, sticky="ew")

            row_f.bind("<Button-1>", lambda e, u=url, f=row_f: self._select_row(u, f))
            for child in row_f.winfo_children():
                if child is not clip:
                    child.bind("<Button-1>", lambda e, u=url, f=row_f: self._select_row(u, f))

            self._row_frames.append(row_f)

    def _copy_to_clipboard(self, url: str):
        self.clipboard_clear()
        self.clipboard_append(url)
        self.update()

    def _select_row(self, url: str, frame: tk.Frame):
        for i, f in enumerate(self._row_frames):
            orig = "#1e1e2e" if i % 2 == 0 else "#16162a"
            f.configure(bg=orig)
            for c in f.winfo_children():
                c.configure(bg=orig)
        frame.configure(bg="#2a3a5e")
        for c in frame.winfo_children():
            c.configure(bg="#2a3a5e")
        self._selected_url = url

    # ── DB actions ────────────────────────────────────────────────────────────
    def _delete_selected(self):
        if not self._selected_url:
            messagebox.showwarning("Nenhum selecionado", "Clique em uma linha para selecionar.")
            return
        if not messagebox.askyesno("Confirmar", f"Apagar este vídeo?\n\n{self._selected_url}"):
            return
        from db import get_db
        get_db().delete_video(self._selected_url)
        self._selected_url = None
        self._refresh_table()

    def _delete_profile(self):
        profile = self.filter_var.get().strip().lstrip("@")
        if not profile:
            messagebox.showwarning("Perfil não informado",
                                   "Preencha 'Filtrar @usuario' com o perfil a apagar.")
            return
        if not messagebox.askyesno("Confirmar", f"Apagar TODOS os vídeos de @{profile}?"):
            return
        from db import get_db
        n = get_db().delete_all(profile=profile)
        messagebox.showinfo("Concluído", f"{n} registro(s) de @{profile} apagados.")
        self._refresh_table()

    def _delete_all(self):
        if not messagebox.askyesno("⚠ Confirmar",
                                   "Apagar TODO o banco?\nEsta ação não pode ser desfeita."):
            return
        from db import get_db
        n = get_db().delete_all()
        messagebox.showinfo("Concluído", f"{n} registro(s) apagados.")
        self._refresh_table()

    def _reset_errors(self):
        profile = self.filter_var.get().strip().lstrip("@") or None
        from db import get_db
        n = get_db().reset_errors(profile=profile)
        messagebox.showinfo("Concluído", f"{n} erro(s) resetados para 'pending'.")
        self._refresh_table()

    def _refetch_descriptions(self):
        if self._running:
            return
        profile = self.filter_var.get().strip().lstrip("@") or None
        self._running = True
        self._append_log("─" * 60)
        self._append_log(f"▶ Re-buscando descrições" + (f" para @{profile}" if profile else " (todos os perfis)"))
        threading.Thread(target=self._worker_refetch, args=(profile,), daemon=True).start()

    def _worker_refetch(self, profile):
        orig_out, orig_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = QueueWriter(self._log_queue)
        try:
            from db import get_db
            from downloader import fetch_descriptions
            db      = get_db()
            records = db.get_all(profile=profile)
            empty   = [r for r in records if not r.description.strip()]
            if not empty:
                self._log_queue.put("✔ Todos os registros já têm descrição.")
                return
            fetch_descriptions(empty, cookies_path=self.cookies_var.get().strip(), workers=5)
            after  = db.get_all(profile=profile)
            filled = sum(1 for r in after if r.description.strip())
            self._log_queue.put(f"✔ {filled}/{len(after)} registros com descrição.")
        except Exception as e:
            self._log_queue.put(f"✖ Erro: {e}")
        finally:
            sys.stdout, sys.stderr = orig_out, orig_err
            self._running = False
            self.after(0, self._refresh_table)

    # ── Settings (persist username history) ──────────────────────────────────
    SETTINGS_PATH = Path(__file__).parent / "settings.json"

    def _load_settings(self) -> dict:
        try:
            if self.SETTINGS_PATH.exists():
                import json
                return json.loads(self.SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_settings(self) -> None:
        try:
            import json
            self.SETTINGS_PATH.write_text(
                json.dumps(self._settings, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _add_to_history(self, username: str) -> None:
        """Add username to history (max 10), most recent first."""
        handle = username.strip().lstrip("@")
        if not handle:
            return
        history: list = self._settings.get("username_history", [])
        if handle in history:
            history.remove(handle)
        history.insert(0, handle)
        self._settings["username_history"] = history[:10]
        self._save_settings()
        self.username_combo.configure(values=history[:10])

    # ── Shared helpers ────────────────────────────────────────────────────────
    def _lbl(self, parent, text: str, row: int = 0):
        ctk.CTkLabel(parent, text=text, anchor="w",
                     font=ctk.CTkFont(size=12), text_color="gray80"
                     ).grid(row=row, column=0, sticky="ew", padx=14, pady=(8, 2))

    def _pick_cookies(self):
        p = filedialog.askopenfilename(
            title="Selecionar cookies",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
        )
        if p:
            self.cookies_var.set(p)

    def _pick_output(self):
        p = filedialog.askdirectory(title="Selecionar pasta de destino")
        if p:
            self.output_var.set(p)

    def _clear_output(self):
        output = self.output_var.get().strip()
        if not output or not Path(output).exists():
            messagebox.showwarning("Pasta não encontrada", f"A pasta não existe:\n{output}")
            return
        files = list(Path(output).glob("*.mp4")) + list(Path(output).glob("*.txt"))
        if not files:
            messagebox.showinfo("Pasta vazia", "Nenhum arquivo .mp4 ou .txt encontrado.")
            return
        if not messagebox.askyesno(
            "⚠ Confirmar",
            f"Apagar {len(files)} arquivo(s) de:\n{output}\n\nEsta ação não pode ser desfeita."
        ):
            return
        errors = []
        for f in files:
            try:
                f.unlink()
            except Exception as e:
                errors.append(f"{f.name}: {e}")
        if errors:
            messagebox.showwarning("Atenção", "Alguns arquivos não puderam ser removidos:\n" + "\n".join(errors))
        else:
            self._append_log(f"🗑 {len(files)} arquivo(s) removidos de: {output}")

    # ── Log ───────────────────────────────────────────────────────────────────
    def _append_log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _poll_logs(self):
        try:
            while True:
                self._append_log(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    # ── Validation ────────────────────────────────────────────────────────────
    def _validate_base(self) -> bool:
        if not self.username_var.get().strip():
            self._append_log("✖ Preencha o campo @usuario.")
            return False
        return True

    def _validate_cookies(self) -> bool:
        if not Path(self.cookies_var.get()).exists():
            self._append_log("✖ Arquivo de cookies não encontrado.")
            return False
        return True

    # ── Metadata cleaner ─────────────────────────────────────────────────────

    def _start_clean_metadata(self):
        if self._running:
            self._append_log("⏳ Aguarde a operação atual terminar.")
            return
        output = self.output_var.get().strip()
        if not output or not Path(output).exists():
            self._append_log("✖ Pasta de destino não encontrada.")
            return

        qty_str = self.qty_var.get().strip()
        qty     = int(qty_str) if qty_str and qty_str.isdigit() and int(qty_str) > 0 else None
        qty_msg = f"{qty} vídeo(s)" if qty else "todos os vídeos"

        from tkinter import messagebox
        if not messagebox.askyesno(
            "🍎 Limpar Metadados",
            f"Processar {qty_msg} em:\n{output}\n\n"
            "Cada vídeo receberá metadados de iPhone 15 Pro e será salvo como .MOV.\n"
            "Os arquivos .mp4 originais serão apagados após conversão.\n\n"
            "Deseja continuar?\n\n"
            "⚠ Requer ffmpeg e exiftool instalados no PATH.",
        ):
            return

        self._lock("⏳  Processando...")
        self._append_log("─" * 60)
        self._append_log(f"▶ Limpeza de metadados — {qty_msg} — perfil iPhone 15 Pro")
        threading.Thread(target=self._worker_clean_metadata,
                         args=(output, qty), daemon=True).start()

    def _worker_clean_metadata(self, output_dir: str, limit: int | None):
        orig_out, orig_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = QueueWriter(self._log_queue)
        try:
            from metadata_cleaner import clean_directory, _check_deps
            ok, missing = _check_deps()
            if not ok:
                self._log_queue.put(
                    f"✖ Dependências ausentes: {', '.join(missing)}\n"
                    "  Instale ffmpeg (https://ffmpeg.org) e\n"
                    "  exiftool (https://exiftool.org) e adicione ao PATH."
                )
                return

            generated = clean_directory(
                directory=output_dir,
                pattern="*.mp4",
                limit=limit,
                overwrite=False,
                log_fn=lambda msg: self._log_queue.put(msg),
                state_json_path=r"C:\!projects\raspafacil\rf-kwai-uploader\state.json",
            )
            if generated:
                self._log_queue.put(
                    f"\n✔ {len(generated)} arquivo(s) .MOV gerado(s) em: {output_dir}"
                )
            else:
                self._log_queue.put("✔ Nenhum arquivo novo para processar.")
        except Exception as e:
            self._log_queue.put(f"✖ Erro na limpeza de metadados: {e}")
        finally:
            sys.stdout, sys.stderr = orig_out, orig_err
            self.after(0, self._unlock)

    # ── Lock / unlock ─────────────────────────────────────────────────────────
    def _lock(self, label: str):
        self._running = True
        self.scrape_btn.configure(state="disabled", text="⏳  Aguarde...")
        self.download_btn.configure(state="disabled", text=label)

    def _unlock(self):
        self._running = False
        self.scrape_btn.configure(state="normal", text="🔍  Coletar tudo")
        self.download_btn.configure(state="normal", text="⬇  Baixar")
        self._refresh_table()

    # ── Workers ───────────────────────────────────────────────────────────────
    def _start_scrape(self):
        if self._running or not self._validate_base() or not self._validate_cookies():
            return
        self._lock("⏳  Coletando...")
        self.scrape_btn.configure(text="⏳  Coletando...")
        self._append_log("─" * 60)
        self._append_log("▶ Coletar tudo (sem download)")
        self._add_to_history(self.username_var.get())
        threading.Thread(target=self._worker_scrape, daemon=True).start()

    def _worker_scrape(self):
        orig_out, orig_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = QueueWriter(self._log_queue)
        try:
            from scraper import scrape_profile
            records = scrape_profile(
                self.username_var.get().strip(),
                cookies_path=self.cookies_var.get().strip(),
                max_videos=None,
            )
            msg = (f"✔ {len(records)} vídeo(s) novo(s) adicionados."
                   if records else "✔ Nenhum vídeo novo.")
            self._log_queue.put(msg)
        except Exception as e:
            self._log_queue.put(f"✖ Erro: {e}")
        finally:
            sys.stdout, sys.stderr = orig_out, orig_err
            self.after(0, self._unlock)

    def _start_download(self):
        if self._running or not self._validate_base():
            return
        qty = self.qty_var.get().strip()
        if qty and not qty.isdigit():
            self._append_log("✖ Quantidade deve ser um número.")
            return
        self._lock("⏳  Baixando...")
        self._append_log("─" * 60)
        self._append_log("▶ Download de pendentes")
        self._add_to_history(self.username_var.get())
        threading.Thread(target=self._worker_download, daemon=True).start()

    def _worker_download(self):
        orig_out, orig_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = QueueWriter(self._log_queue)
        try:
            from db import get_db
            from downloader import download_records

            username = self.username_var.get().strip().lstrip("@")
            output   = self.output_var.get().strip()
            qty_str  = self.qty_var.get().strip()
            qty      = int(qty_str) if qty_str and int(qty_str) > 0 else None

            pending = get_db().get_pending(profile=username)
            if not pending:
                self._log_queue.put(f"✔ Nenhum vídeo pendente para @{username}.")
                self._log_queue.put("  Dica: use 'Coletar tudo' primeiro.")
                return

            batch = pending[:qty] if qty else pending
            self._log_queue.put(f"· {len(pending)} pendente(s) — baixando {len(batch)}")
            download_records(batch, output, cookies_path=self.cookies_var.get().strip())
            self._log_queue.put(f"\n✔ {len(batch)} vídeo(s) baixado(s) em: {output}")
        except Exception as e:
            self._log_queue.put(f"✖ Erro: {e}")
        finally:
            sys.stdout, sys.stderr = orig_out, orig_err
            self.after(0, self._unlock)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
