import argparse, hashlib, json, os, re, sqlite3, subprocess, sys, tempfile, tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path

APP_NAME = "Miralay IFS Explorer"
DB_PATH = Path(os.getenv("LOCALAPPDATA", Path.home())) / "MiralayIFSExplorer" / "data.db"
IFS_URL = "https://ifs10app2.teknorot.com:48080"
SYSTEM_NAME = "TEKNOROT IFS10.10 PROD"
MAX_ROWS = 500

def root_path():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,name TEXT,lu TEXT,view_name TEXT,copy_text TEXT,fields TEXT,key_fields TEXT,interval_minutes INTEGER DEFAULT 60,enabled INTEGER DEFAULT 1,last_run TEXT,last_status TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,source_id INTEGER,fetched_at TEXT,row_json TEXT,row_hash TEXT,change_type TEXT)""")
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
        r.title(APP_NAME); r.geometry("1120x760"); r.minsize(900, 600)
        pan = ttk.Panedwindow(r, orient=tk.HORIZONTAL); pan.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(pan, padding=10); right = ttk.Frame(pan, padding=12)
        pan.add(left, weight=1); pan.add(right, weight=4)
        ttk.Label(left, text="MIRALAY IFS", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=8)
        self.lst = tk.Listbox(left, exportselection=False); self.lst.pack(fill=tk.BOTH, expand=True)
        self.lst.bind("<<ListboxSelect>>", self.select)
        ttk.Button(left, text="+ Yeni veri kaynağı", command=self.new).pack(fill=tk.X, pady=5)
        ttk.Button(left, text="Kaynağı sil", command=self.delete).pack(fill=tk.X)
        ttk.Label(right, text="Veri kaynağı", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        f = ttk.Frame(right); f.pack(fill=tk.X, pady=8)
        ttk.Label(f, text="Kaynak adı").grid(row=0, column=0)
        self.name = ttk.Entry(f, width=35); self.name.grid(row=0, column=1, padx=8, sticky="ew")
        ttk.Label(f, text="Aralık (dakika)").grid(row=0, column=2)
        self.interval = ttk.Entry(f, width=8); self.interval.insert(0, "60"); self.interval.grid(row=0, column=3, padx=8)
        f.columnconfigure(1, weight=1)
        ttk.Label(right, text="IFS ekranından kopyaladığın !IFS.COPYOBJECT bloğunu yapıştır:").pack(anchor="w")
        self.raw = tk.Text(right, height=13, wrap=tk.NONE); self.raw.pack(fill=tk.X, pady=6)
        b = ttk.Frame(right); b.pack(fill=tk.X, pady=5)
        ttk.Button(b, text="Alanları düzenle / Kaydet", command=self.save).pack(side=tk.LEFT, padx=3)
        ttk.Button(b, text="Şimdi Çek", command=self.fetch).pack(side=tk.LEFT, padx=3)
        ttk.Button(b, text="Zamanlamayı Kur", command=self.schedule).pack(side=tk.LEFT, padx=3)
        self.status = ttk.Label(right, text="COPYOBJECT bloğunu yapıştırıp Alanları düzenle / Kaydet'e bas.")
        self.status.pack(anchor="w", pady=8)
        self.tree = ttk.Treeview(right, columns=("date", "kind", "data"), show="headings")
        for col, title, width in [("date", "Tarih", 150), ("kind", "Durum", 100), ("data", "Kayıt", 700)]:
            self.tree.heading(col, text=title); self.tree.column(col, width=width)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.refresh(); r.protocol("WM_DELETE_WINDOW", self.close)

    def refresh(self):
        self.lst.delete(0, tk.END)
        for name, in self.c.execute("SELECT name FROM sources ORDER BY id"):
            self.lst.insert(tk.END, name)
        self.load_rows()

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
        if not rows: raise RuntimeError("Sorgu kayıt döndürmedi. Filtre değerlerini ve alan adlarını kontrol et.")
        new = changed = 0
        for row in rows:
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            old = self.c.execute("SELECT row_hash FROM snapshots WHERE source_id=? AND row_json=? ORDER BY id DESC LIMIT 1", (sid, key)).fetchone()
            kind = "NEW" if old is None else ("UNCHANGED" if old[0] == digest else "CHANGED")
            new += kind == "NEW"; changed += kind == "CHANGED"
            self.c.execute("INSERT INTO snapshots(source_id,fetched_at,row_json,row_hash,change_type) VALUES(?,?,?,?,?)", (sid, now, encoded, digest, kind))
        self.c.execute("UPDATE sources SET last_run=?,last_status=? WHERE id=?", (now, f"{len(rows)} kayıt; yeni {new}; değişen {changed}", sid))
        self.c.commit()
        return f"{len(rows)} kayıt alındı. Yeni: {new}, değişen: {changed}"

    def fetch(self):
        if not self.sid: messagebox.showwarning("Kaynak", "Önce kaynağı kaydet."); return
        try:
            self.status.config(text="IFS oturumu açılıyor..."); self.r.update_idletasks()
            msg = self.execute_sync(self.sid); self.status.config(text=msg); self.load_rows()
            messagebox.showinfo("Tamamlandı", msg)
        except Exception as e:
            self.status.config(text="Hata: " + str(e)); messagebox.showerror("IFS hatası", str(e))

    def load_rows(self):
        self.tree.delete(*self.tree.get_children())
        if self.sid:
            for dt, kind, data in self.c.execute("SELECT fetched_at,change_type,row_json FROM snapshots WHERE source_id=? ORDER BY id DESC LIMIT 100", (self.sid,)):
                self.tree.insert("", tk.END, values=(dt, kind, data[:700]))

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
