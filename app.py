import argparse, hashlib, json, os, re, sqlite3, subprocess, sys, tempfile, tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path

APP_NAME="Miralay IFS Explorer"
DB_PATH=Path(os.getenv("LOCALAPPDATA",Path.home()))/"MiralayIFSExplorer"/"data.db"
IFS_URL="https://ifs10app2.teknorot.com:48080"
SYSTEM_NAME="TEKNOROT IFS10.10 PROD"

def root_path():
    return Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))
def db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,name TEXT,lu TEXT,view_name TEXT,copy_text TEXT,fields TEXT,key_fields TEXT,interval_minutes INTEGER DEFAULT 60,enabled INTEGER DEFAULT 1,last_run TEXT,last_status TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,source_id INTEGER,fetched_at TEXT,row_json TEXT,row_hash TEXT,change_type TEXT)""")
    c.commit()
    return c
def parse_copy(raw):
    lu=re.search(r'^\s*\$LU\s*=\s*([A-Za-z0-9_]+)',raw,re.M)
    view=re.search(r'^\s*\$VIEW\s*=\s*([A-Za-z0-9_]+)',raw,re.M)
    found=[]
    for line in raw.splitlines():
        m=re.match(r'^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$',line)
        if m and m.group(1).upper() not in ("LU","VIEW","RECORD"):
            if not any(x["name"]==m.group(1).upper() for x in found):
                found.append({"name":m.group(1).upper(),"value":m.group(2).strip()})
    if not view: raise ValueError("Kopyalanan blokta $VIEW bulunamadı.")
    if not found: raise ValueError("Kopyalanan blokta alan bulunamadı.")
    return lu.group(1) if lu else "",view.group(1),found

class App:
    def __init__(self,r):
        self.r=r; self.c=db(); self.sid=None
        r.title(APP_NAME); r.geometry("1050x700")
        p=ttk.Panedwindow(r,orient=tk.HORIZONTAL); p.pack(fill=tk.BOTH,expand=True)
        left=ttk.Frame(p,padding=10); right=ttk.Frame(p,padding=12); p.add(left,weight=1); p.add(right,weight=4)
        ttk.Label(left,text="MIRALAY IFS",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=8)
        self.lst=tk.Listbox(left,exportselection=False); self.lst.pack(fill=tk.BOTH,expand=True); self.lst.bind("<<ListboxSelect>>",self.select)
        ttk.Button(left,text="+ Yeni veri kaynağı",command=self.new).pack(fill=tk.X,pady=5)
        ttk.Button(left,text="Kaynağı sil",command=self.delete).pack(fill=tk.X)
        ttk.Label(right,text="Veri kaynağı",font=("Segoe UI",16,"bold")).pack(anchor="w")
        f=ttk.Frame(right); f.pack(fill=tk.X,pady=8)
        ttk.Label(f,text="Kaynak adı").grid(row=0,column=0)
        self.name=ttk.Entry(f,width=35); self.name.grid(row=0,column=1,padx=8,sticky="ew")
        ttk.Label(f,text="Aralık (dakika)").grid(row=0,column=2)
        self.interval=ttk.Entry(f,width=8); self.interval.insert(0,"60"); self.interval.grid(row=0,column=3,padx=8)
        f.columnconfigure(1,weight=1)
        ttk.Label(right,text="IFS ekranından kopyaladığın !IFS.COPYOBJECT bloğunu yapıştır:").pack(anchor="w")
        self.raw=tk.Text(right,height=13,wrap=tk.NONE); self.raw.pack(fill=tk.X,pady=6)
        b=ttk.Frame(right); b.pack(fill=tk.X,pady=5)
        ttk.Button(b,text="Kaydet / Güncelle",command=self.save).pack(side=tk.LEFT,padx=3)
        ttk.Button(b,text="Şimdi Çek",command=self.fetch).pack(side=tk.LEFT,padx=3)
        ttk.Button(b,text="Zamanlamayı Kur",command=self.schedule).pack(side=tk.LEFT,padx=3)
        self.status=ttk.Label(right,text="Bir kaynak seç veya yeni kaynak ekle."); self.status.pack(anchor="w",pady=8)
        self.tree=ttk.Treeview(right,columns=("date","kind","data"),show="headings")
        for col,title,w in [("date","Tarih",150),("kind","Durum",100),("data","Kayıt",650)]:
            self.tree.heading(col,text=title); self.tree.column(col,width=w)
        self.tree.pack(fill=tk.BOTH,expand=True)
        self.refresh(); r.protocol("WM_DELETE_WINDOW",self.close)
    def refresh(self):
        self.lst.delete(0,tk.END)
        for name, in self.c.execute("SELECT name FROM sources ORDER BY id"): self.lst.insert(tk.END,name)
        self.load_rows()
    def select(self,_=None):
        ix=self.lst.curselection()
        if not ix:return
        ids=self.c.execute("SELECT id FROM sources ORDER BY id").fetchall()
        self.sid=ids[ix[0]][0]
        s=self.c.execute("SELECT name,copy_text,interval_minutes,view_name,key_fields,lu FROM sources WHERE id=?",(self.sid,)).fetchone()
        self.name.delete(0,tk.END); self.name.insert(0,s[0])
        self.raw.delete("1.0",tk.END); self.raw.insert("1.0",s[1])
        self.interval.delete(0,tk.END); self.interval.insert(0,str(s[2]))
        self.status.config(text=f"LU: {s[5] or '-'} | VIEW: {s[3]} | Anahtar: {s[4]}")
        self.load_rows()
    def new(self):
        self.sid=None; self.name.delete(0,tk.END); self.raw.delete("1.0",tk.END)
        self.interval.delete(0,tk.END); self.interval.insert(0,"60")
        self.status.config(text="COPYOBJECT bloğunu yapıştır ve kaydet."); self.tree.delete(*self.tree.get_children())
    def save(self):
        try:
            raw=self.raw.get("1.0",tk.END).strip(); lu,view,fields=parse_copy(raw)
            name=self.name.get().strip() or view; mins=int(self.interval.get())
            if mins<1: raise ValueError("Aralık en az 1 dakika olmalı.")
            names=[x["name"] for x in fields]
            keys=[x for x in ("CONTRACT","PART_NO","ORDER_NO","LINE_NO","RELEASE_NO","SEQUENCE_NO") if x in names]
            if not keys: keys=[names[0]]
            keys=",".join(keys)
            if self.sid:
                self.c.execute("UPDATE sources SET name=?,lu=?,view_name=?,copy_text=?,fields=?,key_fields=?,interval_minutes=? WHERE id=?",(name,lu,view,raw,json.dumps(fields,ensure_ascii=False),keys,mins,self.sid))
            else:
                cur=self.c.execute("INSERT INTO sources(name,lu,view_name,copy_text,fields,key_fields,interval_minutes) VALUES(?,?,?,?,?,?,?)",(name,lu,view,raw,json.dumps(fields,ensure_ascii=False),keys,mins)); self.sid=cur.lastrowid
            self.c.commit(); self.refresh()
            messagebox.showinfo("Kaydedildi",f"Başlangıç anahtar alanları: {keys}\nBunların kaydı benzersiz tanımladığını doğrula. Bu sürüm kopyalanan satırı tekrar sorgular; tüm tabloyu taramaz.")
        except Exception as e: messagebox.showerror("Kaydetme hatası",str(e))
    def delete(self):
        if not self.sid:return
        if not messagebox.askyesno("Sil","Kaynak ve geçmiş kayıtları tamamen silinsin mi?"):return
        self.c.execute("DELETE FROM snapshots WHERE source_id=?",(self.sid,)); self.c.execute("DELETE FROM sources WHERE id=?",(self.sid,)); self.c.commit(); self.sid=None; self.new(); self.refresh()
    def make_config(self,sid):
        s=self.c.execute("SELECT view_name,fields,key_fields FROM sources WHERE id=?",(sid,)).fetchone()
        if not s: raise ValueError("Kaynak bulunamadı.")
        fields=json.loads(s[1]); values={x["name"]:x["value"] for x in fields}; keys=[x.strip() for x in s[2].split(",") if x.strip()]
        if not keys or any(k not in values for k in keys): raise ValueError("Anahtar alan bulunamadı.")
        return {"view":s[0],"fields":[x["name"] for x in fields],"keys":{k:values[k] for k in keys},"ifs_url":IFS_URL,"system_name":SYSTEM_NAME}
    def execute_sync(self,sid):
        with tempfile.TemporaryDirectory() as td:
            cfg=Path(td)/"request.json"; out=Path(td)/"result.json"; cfg.write_text(json.dumps(self.make_config(sid),ensure_ascii=False),encoding="utf-8")
            bridge=root_path()/"powershell"/"ifs_bridge.ps1"
            p=subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(bridge),"-ConfigPath",str(cfg),"-OutputPath",str(out)],capture_output=True,text=True,timeout=180)
            if p.returncode or not out.exists(): raise RuntimeError((p.stderr or p.stdout or "IFS bağlantı hatası")[-3000:])
            result=json.loads(out.read_text(encoding="utf-8-sig"))
        rows=result.get("rows",[]); now=datetime.now().isoformat(timespec="seconds")
        if not rows: raise RuntimeError("Filtreli sorgu kayıt döndürmedi.")
        new=changed=0
        for row in rows:
            encoded=json.dumps(row,ensure_ascii=False,sort_keys=True); digest=hashlib.sha256(encoded.encode()).hexdigest()
            old=self.c.execute("SELECT row_hash FROM snapshots WHERE source_id=? ORDER BY id DESC LIMIT 1",(sid,)).fetchone()
            kind="NEW" if old is None else ("UNCHANGED" if old[0]==digest else "CHANGED")
            new+=kind=="NEW"; changed+=kind=="CHANGED"
            self.c.execute("INSERT INTO snapshots(source_id,fetched_at,row_json,row_hash,change_type) VALUES(?,?,?,?,?)",(sid,now,encoded,digest,kind))
        self.c.execute("UPDATE sources SET last_run=?,last_status=? WHERE id=?",(now,f"{len(rows)} kayıt; yeni {new}; değişen {changed}",sid)); self.c.commit()
        return f"{len(rows)} kayıt alındı. Yeni: {new}, değişen: {changed}"
    def fetch(self):
        if not self.sid: messagebox.showwarning("Kaynak","Önce kaynak kaydet."); return
        try:
            self.status.config(text="IFS oturumu açılıyor..."); self.r.update_idletasks()
            msg=self.execute_sync(self.sid); self.status.config(text=msg); self.load_rows(); messagebox.showinfo("Tamamlandı",msg)
        except Exception as e: self.status.config(text="Hata: "+str(e)); messagebox.showerror("IFS hatası",str(e))
    def load_rows(self):
        self.tree.delete(*self.tree.get_children())
        if self.sid:
            for dt,kind,data in self.c.execute("SELECT fetched_at,change_type,row_json FROM snapshots WHERE source_id=? ORDER BY id DESC LIMIT 100",(self.sid,)):
                self.tree.insert("",tk.END,values=(dt,kind,data[:600]))
    def schedule(self):
        if not self.sid: messagebox.showwarning("Kaynak","Önce kaynak seç."); return
        mins=int(self.c.execute("SELECT interval_minutes FROM sources WHERE id=?",(self.sid,)).fetchone()[0])
        command=f'"{sys.executable}" --sync-source {self.sid}' if getattr(sys,"frozen",False) else f'"{sys.executable}" "{Path(__file__).resolve()}" --sync-source {self.sid}'
        task=f"MiralayIFS_{self.sid}"
        ps=f'$a=New-ScheduledTaskAction -Execute "cmd.exe" -Argument \'/c {command}\'; $t=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes({mins}) -RepetitionInterval (New-TimeSpan -Minutes {mins}); Register-ScheduledTask -TaskName "{task}" -Action $a -Trigger $t -Description "Miralay IFS veri takibi" -Force'
        try:
            subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],check=True,capture_output=True,text=True)
            messagebox.showinfo("Zamanlama",f"{mins} dakikada bir görev kuruldu. Bilgisayar açık olmalı; IFS giriş penceresi açılabilir.")
        except Exception as e: messagebox.showerror("Zamanlama hatası",str(e))
    def close(self): self.c.close(); self.r.destroy()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--sync-source",type=int); args=parser.parse_args()
    if args.sync_source:
        c=db()
        try:
            class Worker: pass
            w=Worker(); w.c=c
            w.make_config=lambda sid: App.make_config(w,sid)
            w.execute_sync=lambda sid: App.execute_sync(w,sid)
            print(w.execute_sync(args.sync_source)); c.close(); return 0
        except Exception as e: print(str(e),file=sys.stderr); c.close(); return 1
    r=tk.Tk(); App(r); r.mainloop()
if __name__=="__main__": main()
