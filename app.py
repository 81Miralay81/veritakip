import argparse, getpass, hashlib, json, os, re, sqlite3, subprocess, sys, tempfile, tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path

APP_NAME = "Miralay IFS Explorer"
DB_PATH = Path(os.getenv("LOCALAPPDATA", Path.home())) / "MiralayIFSExplorer" / "data.db"
IFS_URL = "https://ifs10app2.teknorot.com:48080"
SYSTEM_NAME = "TEKNOROT IFS10.10 PROD"
MAX_ROWS = 500
COLORS = {
    "background": "#0b0d1c", "panel": "#151931", "panel_light": "#21274a",
    "border": "#343a66", "input": "#1e2344", "text": "#eef1fc",
    "muted": "#9aa5ca", "purple": "#6026a0", "blue": "#3b82f6",
    "cyan": "#06b6d4", "green": "#22c55e", "danger": "#ef4444",
}

def root_path():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,name TEXT,lu TEXT,view_name TEXT,copy_text TEXT,fields TEXT,key_fields TEXT,interval_minutes INTEGER DEFAULT 60,enabled INTEGER DEFAULT 1,last_run TEXT,last_status TEXT,visible_columns TEXT)""")
    source_columns = {row[1] for row in c.execute("PRAGMA table_info(sources)")}
    if "visible_columns" not in source_columns:
        c.execute("ALTER TABLE sources ADD COLUMN visible_columns TEXT")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,source_id INTEGER,fetched_at TEXT,row_json TEXT,row_hash TEXT,change_type TEXT,row_key TEXT)""")
    snapshot_columns = {row[1] for row in c.execute("PRAGMA table_info(snapshots)")}
    if "row_key" not in snapshot_columns:
        c.execute("ALTER TABLE snapshots ADD COLUMN row_key TEXT")
    c.commit()
    return c

def parse_copy(raw):
    lu = re.search(r'^\s*\$LU\s*=\s*([A-Za-z0-9_]+)', raw, re.M)
    view = re.search(r'^\s*\$VIEW\s*=\s*([A-Za-z0-9_]+)', raw, re.M)
    if not view:
        raise ValueError("İlk satırlarda $VIEW bulunamadı.")
    found = []
    for line in raw.splitlines():
        m = re.match(r'^\s*-\$\d+\s*:\s*(.*?)\s*=\s*(.*?)\s*$', line)
        if not m:
            m = re.match(r'^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$', line)
        if not m:
            continue
        expression, value = m.group(1).strip(), m.group(2).strip()
        # Only plain database column names can be used in SQL filters.
        queryable = bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', expression))
        name = expression.upper() if queryable else expression
        found.append({"name": name, "expression": expression, "value": value,
                      "queryable": queryable, "enabled": False})
    if not found:
        raise ValueError("COPYOBJECT içinde alan satırı bulunamadı.")
    return lu.group(1) if lu else "", view.group(1), found

class App:
    def __init__(self, r):
        self.r, self.c, self.sid = r, db(), None
        r.title(APP_NAME); r.geometry("1360x830"); r.minsize(1080, 700)
        r.configure(bg=COLORS["background"])
        try:
            r.iconbitmap(str(root_path() / "assets" / "uygulama.ico"))
        except Exception:
            pass
        style = ttk.Style()
        try: style.theme_use("clam")
        except tk.TclError: pass
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("Inset.TFrame", background=COLORS["panel_light"])
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"], font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background=COLORS["background"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=("Segoe UI", 9))
        style.configure("PanelMuted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=COLORS["background"], foreground=COLORS["text"], font=("Segoe UI Semibold", 17))
        style.configure("Section.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=("Segoe UI Semibold", 11))
        style.configure("TButton", font=("Segoe UI Semibold", 9), padding=(11, 8), background=COLORS["panel_light"], foreground=COLORS["text"], borderwidth=0, relief="flat")
        style.map("TButton", background=[("disabled", "#222642"), ("pressed", "#343a66"), ("active", "#343a66")], foreground=[("disabled", "#737d9f")])
        for name, color in (("Primary", COLORS["blue"]), ("Accent", COLORS["purple"]), ("Success", "#149c68"), ("Danger", "#b93658"), ("Cyan", "#089bb8")):
            style.configure(f"{name}.TButton", background=color, foreground="#ffffff", font=("Segoe UI Semibold", 9), padding=(12, 8), borderwidth=0, relief="flat")
            style.map(f"{name}.TButton", background=[("disabled", "#343a55"), ("pressed", "#343a66"), ("active", COLORS["purple"] if name == "Primary" else color)])
        style.configure("TEntry", fieldbackground=COLORS["input"], foreground=COLORS["text"], insertcolor=COLORS["text"], bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"], padding=7)
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"], foreground=COLORS["text"], rowheight=31, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#30216f", foreground="#ffffff", font=("Segoe UI Semibold", 9), padding=(9, 10), relief="flat", borderwidth=0)
        style.map("Treeview.Heading", background=[("active", "#4d2b95")])
        style.map("Treeview", background=[("selected", "#49328d")], foreground=[("selected", "#ffffff")])
        style.configure("TScrollbar", background=COLORS["panel_light"], troughcolor=COLORS["panel"], bordercolor=COLORS["panel"], arrowcolor=COLORS["muted"])
        pan = ttk.Panedwindow(r, orient=tk.HORIZONTAL); pan.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(pan, padding=10, style="Panel.TFrame"); right = ttk.Frame(pan, padding=16)
        pan.add(left, weight=1); pan.add(right, weight=4)
        brand_panel = tk.Canvas(left, height=54, bg="#201354", highlightthickness=0, bd=0)
        brand_panel.pack(fill=tk.X, pady=(0, 12))
        self.banner_logo = None
        try:
            raw_logo = tk.PhotoImage(file=str(root_path() / "assets" / "logo.png"))
            self.banner_logo = raw_logo.subsample(2, 2)
        except Exception:
            pass
        self.draw_brand_panel(brand_panel)
        brand_panel.bind("<Configure>", lambda event: self.draw_brand_panel(brand_panel))
        source_label = ttk.Label(left, text="VERİ KAYNAKLARI", style="PanelMuted.TLabel", font=("Segoe UI Semibold", 8))
        source_label.pack(anchor="w", padx=3, pady=(0, 5))
        self.lst = tk.Listbox(left, exportselection=False, bg=COLORS["panel"], fg=COLORS["text"],
                              selectbackground="#4d2b95", selectforeground="#ffffff", relief="flat",
                              highlightthickness=1, highlightbackground=COLORS["border"],
                              highlightcolor=COLORS["blue"], activestyle="none", font=("Segoe UI", 10),
                              borderwidth=0)
        self.lst.pack(fill=tk.BOTH, expand=True)
        self.lst.bind("<<ListboxSelect>>", self.select)
        ttk.Button(left, text="＋  Yeni veri kaynağı", command=self.new, style="Accent.TButton").pack(fill=tk.X, pady=(8, 5))
        ttk.Button(left, text="Kaynağı sil", command=self.delete, style="Danger.TButton").pack(fill=tk.X)
        heading = ttk.Frame(right)
        heading.pack(fill=tk.X, pady=(0, 10))
        title_stack = ttk.Frame(heading)
        title_stack.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(title_stack, text="Veri kaynağı", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_stack, text="IFS Applications 10.10  •  Salt okunur bağlantı", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        tk.Label(heading, text=f"Kullanıcı: {getpass.getuser()}", bg=COLORS["background"],
                 fg=COLORS["muted"], font=("Segoe UI", 9)).pack(side=tk.RIGHT, padx=(8, 14), anchor="n", pady=7)
        tk.Label(heading, text="●  PROD", bg="#183c32", fg="#9bf0be", font=("Segoe UI Semibold", 9), padx=12, pady=6).pack(side=tk.RIGHT, anchor="n", pady=5)
        source_card = ttk.Frame(right, padding=12, style="Panel.TFrame")
        source_card.pack(fill=tk.X, pady=(0, 9))
        ttk.Label(source_card, text="KAYNAK AYARLARI", style="PanelMuted.TLabel", font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(0, 8))
        f = ttk.Frame(source_card, style="Panel.TFrame"); f.pack(fill=tk.X)
        ttk.Label(f, text="Kaynak adı", style="Panel.TLabel").grid(row=0, column=0)
        self.name = ttk.Entry(f, width=35); self.name.grid(row=0, column=1, padx=(8, 22), sticky="ew")
        ttk.Label(f, text="Çekme aralığı (dakika)", style="Panel.TLabel").grid(row=0, column=2)
        self.interval = ttk.Entry(f, width=9); self.interval.insert(0, "60"); self.interval.grid(row=0, column=3, padx=(8, 0))
        f.columnconfigure(1, weight=1)
        query_card = ttk.Frame(right, padding=12, style="Panel.TFrame")
        query_card.pack(fill=tk.X, pady=(0, 9))
        query_head = ttk.Frame(query_card, style="Panel.TFrame")
        query_head.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(query_head, text="IFS SORGUSU", style="Panel.TLabel", font=("Segoe UI Semibold", 10)).pack(side=tk.LEFT)
        ttk.Label(query_head, text="IFS ekranından kopyaladığın !IFS.COPYOBJECT bloğunu yapıştır", style="PanelMuted.TLabel").pack(side=tk.LEFT, padx=12)
        text_frame = tk.Frame(query_card, bg=COLORS["input"], highlightthickness=1, highlightbackground=COLORS["border"])
        text_frame.pack(fill=tk.X)
        self.raw = tk.Text(text_frame, height=5, wrap=tk.NONE, bg=COLORS["input"], fg=COLORS["text"],
                           insertbackground=COLORS["text"], selectbackground="#4d2b95", relief="flat",
                           borderwidth=0, font=("Consolas", 9), padx=8, pady=7)
        raw_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.raw.xview)
        self.raw.configure(xscrollcommand=raw_scroll.set)
        self.raw.pack(fill=tk.X)
        raw_scroll.pack(fill=tk.X)
        b = ttk.Frame(right); b.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(b, text="Alanları düzenle / Kaydet", command=self.save, style="Primary.TButton").pack(side=tk.LEFT, padx=(0, 7))
        ttk.Button(b, text="Şimdi Çek", command=self.fetch, style="Success.TButton").pack(side=tk.LEFT, padx=7)
        ttk.Button(b, text="Zamanlamayı Kur", command=self.schedule, style="Accent.TButton").pack(side=tk.LEFT, padx=7)
        self.status = ttk.Label(right, text="COPYOBJECT bloğunu yapıştırıp alanları kaydedin.", style="Muted.TLabel")
        self.status.pack(anchor="w", pady=(1, 4))
        resultbar = ttk.Frame(right); resultbar.pack(fill=tk.X, pady=(6, 4))
        ttk.Label(resultbar, text="Sorgu sonuçları", style="Section.TLabel").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.apply_search())
        ttk.Label(resultbar, text="Ara").pack(side=tk.LEFT, padx=(14, 4))
        search_entry = ttk.Entry(resultbar, textvariable=self.search_var, width=24)
        search_entry.pack(side=tk.LEFT)
        ttk.Button(resultbar, text="Temizle", command=lambda: self.search_var.set("")).pack(side=tk.LEFT, padx=4)
        self.result_count = ttk.Label(resultbar, text="0 kayıt")
        self.result_count.pack(side=tk.LEFT, padx=8)
        ttk.Button(resultbar, text="Sütunları seç", command=self.choose_columns).pack(side=tk.RIGHT, padx=3)
        ttk.Button(resultbar, text="Seçili satırları kopyala", command=self.copy_selected).pack(side=tk.RIGHT, padx=3)
        ttk.Button(resultbar, text="Tüm sonuçları kopyala", command=self.copy_all).pack(side=tk.RIGHT, padx=3)
        tableframe = tk.Frame(right, bg=COLORS["panel"], highlightthickness=1, highlightbackground=COLORS["border"])
        tableframe.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tableframe, columns=("date", "kind"), show="headings", selectmode="extended")
        self.tree.heading("date", text="Çekilme zamanı"); self.tree.column("date", width=145, stretch=False)
        self.tree.heading("kind", text="Değişim"); self.tree.column("kind", width=90, stretch=False)
        ybar = ttk.Scrollbar(tableframe, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(tableframe, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        tableframe.rowconfigure(0, weight=1); tableframe.columnconfigure(0, weight=1)
        self.result_rows = []
        self.displayed_indexes = []
        r.after(150, lambda: pan.sashpos(0, 250))
        self.refresh(); r.protocol("WM_DELETE_WINDOW", self.close)

    def refresh(self):
        self.lst.delete(0, tk.END)
        for name, in self.c.execute("SELECT name FROM sources ORDER BY id"):
            self.lst.insert(tk.END, name)
        self.load_rows()

    def draw_brand_panel(self, canvas):
        """Fill the sidebar brand area with the white-wordmark Kalıp Takip banner."""
        width = max(canvas.winfo_width(), 210)
        height = max(canvas.winfo_height(), 54)
        canvas.delete("all")
        if self.banner_logo is not None:
            canvas.create_image(width // 2, height // 2, image=self.banner_logo, anchor="center")

    def select(self, _=None):
        ix = self.lst.curselection()
        if not ix: return
        ids = self.c.execute("SELECT id FROM sources ORDER BY id").fetchall()
        self.sid = ids[ix[0]][0]
        s = self.c.execute("SELECT name,copy_text,interval_minutes,view_name,key_fields,lu FROM sources WHERE id=?", (self.sid,)).fetchone()
        self.name.delete(0, tk.END); self.name.insert(0, s[0])
        self.raw.delete("1.0", tk.END); self.raw.insert("1.0", s[1])
        self.interval.delete(0, tk.END); self.interval.insert(0, str(s[2]))
        self.status.config(text=f"LU: {s[5] or '-'} | VIEW: {s[3]} | Varsayılan anahtar: {s[4] or '-'}")
        self.load_rows()

    def new(self):
        self.sid = None
        self.name.delete(0, tk.END); self.raw.delete("1.0", tk.END)
        self.interval.delete(0, tk.END); self.interval.insert(0, "60")
        self.status.config(text="COPYOBJECT bloğunu yapıştırıp Alanları düzenle / Kaydet'e bas.")
        self.tree.delete(*self.tree.get_children())

    def save(self):
        try:
            raw = self.raw.get("1.0", tk.END).strip()
            lu, view, fields = parse_copy(raw)
            if self.sid:
                old = self.c.execute("SELECT fields FROM sources WHERE id=?", (self.sid,)).fetchone()
                if old and old[0]:
                    saved = {x.get("expression"): x for x in json.loads(old[0])}
                    for x in fields:
                        if x["expression"] in saved:
                            x["enabled"] = saved[x["expression"]].get("enabled", False)
                            x["value"] = saved[x["expression"]].get("value", x["value"])
            self.open_field_editor(raw, lu, view, fields)
        except Exception as e:
            messagebox.showerror("COPYOBJECT hatası", str(e))

    def open_field_editor(self, raw, lu, view, fields):
        win = tk.Toplevel(self.r); win.title("IFS alanları ve sorgu koşulları")
        win.geometry("980x680"); win.transient(self.r); win.grab_set()
        top = ttk.Frame(win, padding=10); top.pack(fill=tk.X)
        ttk.Label(top, text=f"LU: {lu or '-'}     VIEW: {view}", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(top, text="Sadece seçtiğin gerçek alanlar filtre olur. % = bu alan için filtre uygulama. Tarih aralığı: 01.01.2026..31.01.2026").pack(anchor="w", pady=4)
        outer = ttk.Frame(win); outer.pack(fill=tk.BOTH, expand=True, padx=10)
        canvas = tk.Canvas(outer, highlightthickness=0); sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas); inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw"); canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.RIGHT, fill=tk.Y)
        for col, label in enumerate(("Filtre", "IFS alanı / ifade", "COPYOBJECT değeri", "Sorguda kullanılacak değer")):
            ttk.Label(inner, text=label, font=("Segoe UI", 9, "bold")).grid(row=0, column=col, sticky="w", padx=5, pady=5)
        states = []
        for i, field in enumerate(fields, 1):
            enabled = tk.BooleanVar(value=field.get("enabled", False) and field["queryable"])
            value = tk.StringVar(value=field.get("value", ""))
            cb = ttk.Checkbutton(inner, variable=enabled, state=("normal" if field["queryable"] else "disabled"))
            cb.grid(row=i, column=0, padx=5, sticky="w")
            label = field["expression"]
            ttk.Label(inner, text=label, width=43).grid(row=i, column=1, sticky="w", padx=5, pady=2)
            ttk.Label(inner, text=field.get("value", "")[:38], width=28, foreground=("#555555" if field["queryable"] else "#999999")).grid(row=i, column=2, sticky="w", padx=5)
            ent = ttk.Entry(inner, textvariable=value, width=35, state=("normal" if field["queryable"] else "disabled"))
            ent.grid(row=i, column=3, sticky="ew", padx=5, pady=2)
            states.append((field, enabled, value))
        inner.columnconfigure(3, weight=1)
        bottom = ttk.Frame(win, padding=10); bottom.pack(fill=tk.X)
        ttk.Label(bottom, text="Fonksiyonlu satırlar bilgi amaçlıdır; doğrudan SQL filtresi yapılamaz.").pack(side=tk.LEFT)
        def commit():
            selected = []
            for f, en, val in states:
                f["enabled"] = bool(en.get()) and f["queryable"]
                f["value"] = val.get().strip()
                selected.append(f)
            try:
                mins = int(self.interval.get())
                if mins < 1: raise ValueError("Aralık en az 1 dakika olmalı.")
                name = self.name.get().strip() or view
                key_candidates = [x["name"] for x in selected if x["queryable"] and x["name"] in ("CONTRACT", "PART_NO", "ORDER_NO", "LINE_NO", "RELEASE_NO", "SEQUENCE_NO")]
                keys = ",".join(key_candidates)
                payload = json.dumps(selected, ensure_ascii=False)
                if self.sid:
                    self.c.execute("UPDATE sources SET name=?,lu=?,view_name=?,copy_text=?,fields=?,key_fields=?,interval_minutes=? WHERE id=?", (name, lu, view, raw, payload, keys, mins, self.sid))
                else:
                    cur = self.c.execute("INSERT INTO sources(name,lu,view_name,copy_text,fields,key_fields,interval_minutes) VALUES(?,?,?,?,?,?,?)", (name, lu, view, raw, payload, keys, mins))
                    self.sid = cur.lastrowid
                self.c.commit(); self.refresh()
                self.status.config(text=f"Kaydedildi | {view} | {sum(1 for x in selected if x['enabled'])} filtre alanı seçildi")
                win.destroy()
                messagebox.showinfo("Kaydedildi", "Alanlar kaydedildi.\n\nŞimdi Çek ile sorgulayabilirsin. Sorgu en fazla 500 satır döndürür; tüm alanlar boş veya % ise ilk 500 kayıtla sınırlıdır.")
            except Exception as e:
                messagebox.showerror("Kaydetme hatası", str(e))
        ttk.Button(bottom, text="Seçimleri kaydet", command=commit).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bottom, text="Vazgeç", command=win.destroy).pack(side=tk.RIGHT)

    def delete(self):
        if not self.sid: return
        if not messagebox.askyesno("Sil", "Kaynak ve geçmiş kayıtları tamamen silinsin mi?"): return
        self.c.execute("DELETE FROM snapshots WHERE source_id=?", (self.sid,))
        self.c.execute("DELETE FROM sources WHERE id=?", (self.sid,)); self.c.commit()
        self.sid = None; self.new(); self.refresh()

    def make_config(self, sid):
        s = self.c.execute("SELECT view_name,fields FROM sources WHERE id=?", (sid,)).fetchone()
        if not s: raise ValueError("Kaynak bulunamadı.")
        fields = json.loads(s[1])
        columns = list(dict.fromkeys(x["name"] for x in fields if x.get("queryable")))
        filters = []
        for x in fields:
            if not x.get("queryable") or not x.get("enabled"): continue
            value = x.get("value", "").strip()
            if not value or value == "%": continue
            filters.append({"name": x["name"], "value": value})
        if not columns: raise ValueError("Sorgulanabilir gerçek tablo alanı bulunamadı.")
        return {"view": s[0], "columns": columns, "filters": filters, "max_rows": MAX_ROWS,
                "ifs_url": IFS_URL, "system_name": SYSTEM_NAME}

    def execute_sync(self, sid):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "request.json"; out = Path(td) / "result.json"
            cfg.write_text(json.dumps(self.make_config(sid), ensure_ascii=False), encoding="utf-8")
            bridge = root_path() / "powershell" / "ifs_bridge.ps1"
            p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(bridge), "-ConfigPath", str(cfg), "-OutputPath", str(out)], capture_output=True, text=True, timeout=240)
            if p.returncode or not out.exists():
                raise RuntimeError((p.stderr or p.stdout or "IFS bağlantı hatası")[-3000:])
            result = json.loads(out.read_text(encoding="utf-8-sig"))
        rows = result.get("rows", []); now = datetime.now().isoformat(timespec="seconds")
        if not rows:
            self.c.execute("UPDATE sources SET last_run=?,last_status=? WHERE id=?", (now, "0 kayıt; eşleşen sonuç yok", sid))
            self.c.commit()
            return "Sorgu tamamlandı; bu filtrelerle eşleşen kayıt bulunamadı."
        key_row = self.c.execute("SELECT key_fields FROM sources WHERE id=?", (sid,)).fetchone()
        key_fields = [x for x in (key_row[0] or "").split(",") if x] if key_row else []
        new = changed = 0
        for row in rows:
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            # Compare records by stable business key (e.g. CONTRACT + PART_NO),
            # not by the entire row JSON; otherwise changed records look new.
            if key_fields and all(k in row for k in key_fields):
                row_key = json.dumps([row.get(k) for k in key_fields], ensure_ascii=False)
            else:
                row_key = encoded
            old = self.c.execute("SELECT row_hash FROM snapshots WHERE source_id=? AND row_key=? ORDER BY id DESC LIMIT 1", (sid, row_key)).fetchone()
            kind = "NEW" if old is None else ("UNCHANGED" if old[0] == digest else "CHANGED")
            new += kind == "NEW"; changed += kind == "CHANGED"
            self.c.execute("INSERT INTO snapshots(source_id,fetched_at,row_json,row_hash,change_type,row_key) VALUES(?,?,?,?,?,?)", (sid, now, encoded, digest, kind, row_key))
        self.c.execute("UPDATE sources SET last_run=?,last_status=? WHERE id=?", (now, f"{len(rows)} kayıt; yeni {new}; değişen {changed}", sid))
        self.c.commit()
        return f"{len(rows)} kayıt alındı. Yeni: {new}, değişen: {changed}"

    def show_error(self, title, message):
        # Ayrintili hata metnini secilebilir ve tek tikla kopyalanabilir goster.
        win = tk.Toplevel(self.r); win.title(title); win.geometry("850x420"); win.transient(self.r)
        ttk.Label(win, text="Hata ayrintisi (metni secip kopyalayabilir veya tumunu kopyalayabilirsin):").pack(anchor="w", padx=10, pady=(10, 4))
        frame = ttk.Frame(win); frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        box = tk.Text(frame, wrap=tk.WORD, height=16); scroll = ttk.Scrollbar(frame, command=box.yview)
        box.configure(yscrollcommand=scroll.set); box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scroll.pack(side=tk.RIGHT, fill=tk.Y)
        box.insert("1.0", str(message)); box.configure(state=tk.DISABLED)
        buttons = ttk.Frame(win); buttons.pack(fill=tk.X, padx=10, pady=10)
        def copy_all():
            self.r.clipboard_clear(); self.r.clipboard_append(str(message)); self.r.update()
        ttk.Button(buttons, text="Tüm hatayı kopyala", command=copy_all).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Kapat", command=win.destroy).pack(side=tk.RIGHT)

    def fetch(self):
        if not self.sid: messagebox.showwarning("Kaynak", "Önce kaynağı kaydet."); return
        try:
            proceed = messagebox.askyesno("Sorgu öncesi kontrol",
                f"Bu sorgu en fazla {MAX_ROWS:,} satır getirecek.\n\n"
                "Güvenlik için 500 satırdan fazlası otomatik olarak alınmaz.\n\nDevam edilsin mi?")
            if not proceed:
                self.status.config(text="Sorgu kullanıcı tarafından iptal edildi.")
                return
            self.status.config(text="IFS sorgusu çalıştırılıyor..."); self.r.update_idletasks()
            msg = self.execute_sync(self.sid); self.status.config(text=msg); self.load_rows()
            messagebox.showinfo("Tamamlandı", msg)
        except Exception as e:
            self.status.config(text="IFS bağlantı hatası - ayrıntı penceresini kontrol et.")
            self.show_error("IFS bağlantı hatası", str(e))

    def load_rows(self):
        self.tree.delete(*self.tree.get_children())
        self.result_rows = []
        self.displayed_indexes = []
        records = []
        if self.sid:
            for dt, kind, data in self.c.execute("SELECT fetched_at,change_type,row_json FROM snapshots WHERE source_id=? ORDER BY id DESC LIMIT 500", (self.sid,)):
                try:
                    row = json.loads(data)
                except Exception:
                    row = {"KAYIT": data}
                records.append((dt, kind, row))
        field_names = []
        for _, _, row in records:
            for key in row:
                if key not in field_names:
                    field_names.append(key)
        columns = ["date", "kind"] + [f"f{i}" for i in range(len(field_names))]
        self.field_names = field_names
        visible = None
        if self.sid:
            saved = self.c.execute("SELECT visible_columns FROM sources WHERE id=?", (self.sid,)).fetchone()
            if saved and saved[0]:
                try: visible = set(json.loads(saved[0]))
                except Exception: visible = None
        if visible is None:
            visible = set(field_names)
        self.visible_field_names = [name for name in field_names if name in visible]
        display = ["date", "kind"] + [f"f{field_names.index(name)}" for name in self.visible_field_names]
        self.tree.configure(columns=columns, displaycolumns=display)
        self.tree.heading("date", text="Çekilme zamanı"); self.tree.column("date", width=155, minwidth=155, stretch=False)
        self.tree.tag_configure("NEW", background="#17372d", foreground="#b8f2cf")
        self.tree.tag_configure("CHANGED", background="#3b2d1b", foreground="#ffe0a6")
        self.tree.tag_configure("UNCHANGED", background="#1b203e", foreground="#cbd3ef")
        self.tree.heading("kind", text="Değişim"); self.tree.column("kind", width=95, minwidth=95, stretch=False)
        for i, name in enumerate(field_names):
            col = f"f{i}"
            self.tree.heading(col, text=name)
            self.tree.column(col, width=180, minwidth=110, stretch=False)
        for dt, kind, row in records:
            self.result_rows.append((dt, kind, row))
        self.apply_search()

    def apply_search(self):
        """Filter loaded snapshots in the UI without issuing another IFS query."""
        if not hasattr(self, "tree"):
            return
        query = self.search_var.get().strip().casefold() if hasattr(self, "search_var") else ""
        self.tree.delete(*self.tree.get_children())
        self.displayed_indexes = []
        for index, (dt, kind, row) in enumerate(self.result_rows):
            if not self.row_matches_search(dt, kind, row, query):
                continue
            values = [dt, kind] + [row.get(name, "") for name in getattr(self, "field_names", [])]
            self.tree.insert("", tk.END, iid=f"row-{index}", values=values,
                             tags=(kind if kind in ("NEW", "CHANGED", "UNCHANGED") else "UNCHANGED",))
            self.displayed_indexes.append(index)
        if hasattr(self, "result_count"):
            total = len(self.result_rows)
            shown = len(self.displayed_indexes)
            self.result_count.config(text=f"{shown} / {total} kayıt" if query else f"{total} kayıt")

    @staticmethod
    def row_matches_search(dt, kind, row, query):
        if not query:
            return True
        values = [dt, kind] + [str(value or "") for value in row.values()]
        return any(query in value.casefold() for value in values)

    def choose_columns(self):
        if not self.sid or not getattr(self, "field_names", []):
            messagebox.showinfo("Sütunlar", "Önce bir veri kaynağı seçip sorgu sonucu getir.")
            return
        win = tk.Toplevel(self.r); win.title("Gösterilecek sütunları seç")
        win.geometry("430x560"); win.transient(self.r); win.grab_set()
        ttk.Label(win, text="Listede görmek istediğin sütunları işaretle:").pack(anchor="w", padx=12, pady=10)
        tools = ttk.Frame(win); tools.pack(fill=tk.X, padx=10)
        body = ttk.Frame(win); body.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        canvas = tk.Canvas(body, highlightthickness=0)
        bar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); bar.pack(side=tk.RIGHT, fill=tk.Y)
        current = set(self.visible_field_names)
        states = {}
        for name in self.field_names:
            v = tk.BooleanVar(value=name in current)
            states[name] = v
            ttk.Checkbutton(inner, text=name, variable=v).pack(anchor="w", pady=2)
        def set_all(value):
            for v in states.values(): v.set(value)
        ttk.Button(tools, text="Tümünü seç", command=lambda: set_all(True)).pack(side=tk.LEFT, padx=3)
        ttk.Button(tools, text="Tümünü kaldır", command=lambda: set_all(False)).pack(side=tk.LEFT, padx=3)
        def save():
            chosen = [name for name, v in states.items() if v.get()]
            self.c.execute("UPDATE sources SET visible_columns=? WHERE id=?",
                           (json.dumps(chosen, ensure_ascii=False), self.sid))
            self.c.commit()
            self.load_rows()
            win.destroy()
        bottom = ttk.Frame(win, padding=10); bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Uygula", command=save).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="İptal", command=win.destroy).pack(side=tk.RIGHT)

    def _copy_rows(self, selected_only=False):
        if selected_only:
            indexes = [int(item[4:]) for item in self.tree.selection() if item.startswith("row-")]
            rows = [self.result_rows[i] for i in indexes if i < len(self.result_rows)]
        else:
            rows = self.result_rows
        if not rows:
            messagebox.showinfo("Kopyalama", "Kopyalanacak sonuç bulunamadı.")
            return
        preferred = getattr(self, "visible_field_names", [])
        keys = [key for key in preferred if any(key in row for _, _, row in rows)]
        if not keys:
            for _, _, row in rows:
                for key in row:
                    if key not in keys:
                        keys.append(key)
        lines = ["Çekilme zamanı\tDeğişim\t" + "\t".join(keys)]
        for dt, kind, row in rows:
            vals = [str(row.get(k, "") if row.get(k) is not None else "") for k in keys]
            lines.append("\t".join([dt, kind] + vals))
        self.r.clipboard_clear()
        self.r.clipboard_append("\n".join(lines))
        self.r.update()
        self.status.config(text=f"{len(rows)} satır panoya kopyalandı.")

    def copy_selected(self):
        self._copy_rows(True)

    def copy_all(self):
        self._copy_rows(False)

    def schedule(self):
        if not self.sid: messagebox.showwarning("Kaynak", "Önce kaynak seç."); return
        mins = int(self.c.execute("SELECT interval_minutes FROM sources WHERE id=?", (self.sid,)).fetchone()[0])
        command = f'"{sys.executable}" --sync-source {self.sid}' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}" --sync-source {self.sid}'
        task = f"MiralayIFS_{self.sid}"
        ps = f'$a=New-ScheduledTaskAction -Execute "cmd.exe" -Argument \'/c {command}\'; $t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes({mins}) -RepetitionInterval (New-TimeSpan -Minutes {mins}); Register-ScheduledTask -TaskName "{task}" -Action $a -Trigger $t -Description "Miralay IFS veri takibi" -Force'
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], check=True, capture_output=True, text=True)
            messagebox.showinfo("Zamanlama", f"{mins} dakikada bir görev kuruldu. Bilgisayar açık olmalı; IFS giriş penceresi açılabilir.")
        except Exception as e: messagebox.showerror("Zamanlama hatası", str(e))

    def close(self):
        self.c.close(); self.r.destroy()

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--sync-source", type=int); args = parser.parse_args()
    if args.sync_source:
        c = db()
        try:
            class Worker: pass
            w = Worker(); w.c = c
            w.make_config = lambda sid: App.make_config(w, sid)
            w.execute_sync = lambda sid: App.execute_sync(w, sid)
            print(w.execute_sync(args.sync_source)); c.close(); return 0
        except Exception as e:
            print(str(e), file=sys.stderr); c.close(); return 1
    r = tk.Tk(); App(r); r.mainloop()

if __name__ == "__main__":
    main()
