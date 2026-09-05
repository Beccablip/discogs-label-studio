import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import json, os, threading, requests, pandas as pd, time, shutil
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from PIL import Image, ImageTk

# Give this Python process a unique Windows App ID so it displays custom icons on the taskbar
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DiscogsLabelStudio.App.1")
except Exception:
    pass

# ================= CONFIG =================
CONFIG_FILE = "config.json"
MASTER_CSV = "Vinyl_Labels_Discogs_FULL_SCHEMA.csv"
RATE_LIMIT = 1.1

# Avery 5160 Default (points)
PAGE_WIDTH, PAGE_HEIGHT = letter
LABEL_WIDTH = 189
LABEL_HEIGHT = 72
LEFT_MARGIN = 14
TOP_MARGIN = 36
X_GAP = 9
COLUMNS = 3
ROWS = 10

# Theme
BG = "#0b1920" 
FG = "#e6e6e6"
ACCENT = "#00aced" 
BTN = "#105a75" 

MAX_LOGO_WIDTH = 60
SPIN_SPEED = 0.2
SPIN_INTERVAL = 50

# ================= HELPERS =================
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def normalize_fractions(text):
    return str(text).replace("⅓", " 1/3").replace("⅔", " 2/3").replace("½", " 1/2")

def draw_wrapped_text(c, text, x_center, y_start, max_width, font, size, max_lines, leading=10):
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        if stringWidth(test, font, size) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and current:
        lines.append(current)
    if len(words) > sum(len(l.split()) for l in lines):
        lines[-1] = lines[-1].rstrip() + "…"
    
    c.setFont(font, size)
    for i, line in enumerate(lines):
        c.drawCentredString(x_center, y_start - i * leading, line)

# ================= APP =================
class DiscogsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Discogs Label Studio")
        self.geometry("700x450")
        self.resizable(False, False)
        self.configure(bg=BG)

        # Window Icon
        if os.path.exists("logo.png"):
            icon_img = Image.open("logo.png")
            self.iconphoto(True, ImageTk.PhotoImage(icon_img))

        self.config_data = load_config()
        self.pause_flag = threading.Event()
        self.pause_flag.set()
        self.errors = []
        self.logo_angle = 0

        self.build_ui()

    def build_ui(self):
        # Top Logo & Connection Bar
        top_bar = tk.Frame(self, bg=BG)
        top_bar.pack(fill="x", padx=10, pady=5)

        self.logo_label = tk.Label(top_bar, bg=BG)
        self.logo_label.pack(side="left")

        self.stats_label = tk.Label(top_bar, text="Collector\nCol: 0 | Sale: 0 | Want: 0", bg=BG, fg=FG, justify="right", font=("Arial", 9, "bold"))
        self.stats_label.pack(side="right")

        self.logo_label_right = tk.Label(top_bar, bg=BG)
        self.logo_label_right.pack(side="right", padx=10)

        self.connect_btn = tk.Button(top_bar, text="Connect", bg="#5a9bd4", fg="black", font=("Arial", 10, "bold"), command=self.test_connection)
        self.connect_btn.pack(side="right", padx=10)

        if os.path.exists("logo.png"):
            self.original_logo = Image.open("logo.png").convert("RGBA")
            ratio = MAX_LOGO_WIDTH / float(self.original_logo.width)
            self.original_logo = self.original_logo.resize((int(self.original_logo.width * ratio), int(self.original_logo.height * ratio)), Image.LANCZOS)
            self.animate_logo()

        # Top Header Area
        header_frame = tk.Frame(self, bg=BG)
        header_frame.pack(fill="x", padx=10, pady=5)

        # Build / Update Buttons
        btn_frame = tk.Frame(header_frame, bg=BG)
        btn_frame.pack(side="left", padx=10)
        
        tk.Button(btn_frame, text="Build Master", bg=BTN, fg=FG, width=15, 
                  command=self.run_build).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="Update Master (Sync New)", bg=BTN, fg=FG, width=25, 
                  command=self.run_update).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="Preview First Page", bg=BTN, fg=FG, width=20, 
                  command=lambda: self.run_labels(True)).grid(row=0, column=2, padx=5)

        # Configuration Frame
        config_frame = tk.LabelFrame(self, text="Configuration", bg=BG, fg=FG)
        config_frame.pack(fill="x", padx=15, pady=10)

        tk.Label(config_frame, text="Username:", bg=BG, fg=FG).grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.user_entry = tk.Entry(config_frame, width=30)
        self.user_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.user_entry.insert(0, self.config_data.get("username", ""))

        tk.Label(config_frame, text="API Key:", bg=BG, fg=FG).grid(row=0, column=2, padx=5, pady=5, sticky="e")
        self.api_entry = tk.Entry(config_frame, width=40, show="*")
        self.api_entry.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        self.api_entry.insert(0, self.config_data.get("api_key", ""))

        tk.Label(config_frame, text="Font:", bg=BG, fg=FG).grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.font_var = tk.StringVar(value=self.config_data.get("font", "Helvetica"))
        self.font_combo = ttk.Combobox(config_frame, textvariable=self.font_var, width=27, values=["Helvetica", "Courier", "Times-Roman"])
        self.font_combo.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        tk.Label(config_frame, text="Label Type:", bg=BG, fg=FG).grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.label_type_var = tk.StringVar(value=self.config_data.get("label_type", "5160"))
        radio_frame = tk.Frame(config_frame, bg=BG)
        radio_frame.grid(row=1, column=3, sticky="w")
        tk.Radiobutton(radio_frame, text="5160", variable=self.label_type_var, value="5160", bg=BG, fg=FG, selectcolor=BG).pack(side="left")
        tk.Radiobutton(radio_frame, text="5260", variable=self.label_type_var, value="5260", bg=BG, fg=FG, selectcolor=BG).pack(side="left")
        tk.Radiobutton(radio_frame, text="5060", variable=self.label_type_var, value="5060", bg=BG, fg=FG, selectcolor=BG).pack(side="left")

        # Generation Frame
        gen_frame = tk.LabelFrame(self, text="Generation", bg=BG, fg=FG)
        gen_frame.pack(fill="x", padx=15, pady=5)

        start_frame = tk.Frame(gen_frame, bg=BG)
        start_frame.pack(anchor="w", padx=10, pady=5)
        tk.Label(start_frame, text="Start at Label Position #:", bg=BG, fg=FG).pack(side="left")
        self.start_label = tk.Spinbox(start_frame, from_=1, to=30, width=5)
        self.start_label.pack(side="left", padx=5)

        tk.Button(gen_frame, text="Generate Full Label PDF", bg=ACCENT, fg="black", font=("Arial", 10, "bold"),
                  command=lambda: self.run_labels(False)).pack(fill="x", padx=10, pady=10)

        # Status & Progress
        self.progress = ttk.Progressbar(self, length=670)
        self.progress.pack(pady=10)
        
        self.status = tk.Label(self, text="Ready", bg=BG, fg=FG)
        self.status.pack()

        tk.Button(self, text="Pause / Resume", bg=BTN, fg=FG, command=self.toggle_pause).pack(pady=10)

    def animate_logo(self):
        rotated = self.original_logo.rotate(self.logo_angle, resample=Image.BICUBIC)
        self.logo_img = ImageTk.PhotoImage(rotated)
        self.logo_label.configure(image=self.logo_img)
        if hasattr(self, 'logo_label_right'):
            self.logo_label_right.configure(image=self.logo_img)
        self.logo_angle = (self.logo_angle + SPIN_SPEED) % 360
        self.after(SPIN_INTERVAL, self.animate_logo)

    def test_connection(self):
        username = self.user_entry.get().strip()
        try:
            r = requests.get(f"https://api.discogs.com/users/{username}", headers=self.get_api_headers(), timeout=10)
            if r.status_code == 200:
                d = r.json()
                self.stats_label.config(text=f"Collector\nCol: {d.get('num_collection', 0)} | Sale: {d.get('num_for_sale', 0)} | Want: {d.get('num_wantlist', 0)}")
                self.connect_btn.config(text="Connected", bg="#7a9ddc")
            else:
                messagebox.showerror("Connection Failed", f"Status Code: {r.status_code}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def save_settings(self):
        self.config_data["username"] = self.user_entry.get().strip()
        self.config_data["api_key"] = self.api_entry.get().strip()
        self.config_data["font"] = self.font_var.get()
        self.config_data["label_type"] = self.label_type_var.get()
        save_config(self.config_data)

    def toggle_pause(self):
        if self.pause_flag.is_set():
            self.pause_flag.clear()
            self.status.config(text="Paused")
        else:
            self.pause_flag.set()
            self.status.config(text="Resumed")

    def wait(self):
        while not self.pause_flag.is_set():
            time.sleep(0.2)

    def get_api_headers(self):
        self.save_settings()
        return {
            "Authorization": f"Discogs token={self.config_data.get('api_key', '')}",
            "User-Agent": "DiscogsLabelStudio/1.0"
        }

    # ---------- Build / Update ----------
    def run_build(self):
        threading.Thread(target=self.build_master, daemon=True).start()

    def build_master(self):
        username = self.user_entry.get().strip()
        headers = self.get_api_headers()
        ids, page = [], 1

        while True:
            self.wait()
            try:
                r = requests.get(
                    f"https://api.discogs.com/users/{username}/collection/folders/0/releases?page={page}&per_page=100",
                    headers=headers, timeout=10)
                if r.status_code != 200:
                    break
                data = r.json()
                ids.extend(item["id"] for item in data["releases"])
                if page >= data["pagination"]["pages"]:
                    break
                page += 1
                time.sleep(RATE_LIMIT)
            except Exception as e:
                break

        rows = []
        self.after(0, lambda: self.progress.configure(maximum=len(ids)))

        for i, rid in enumerate(ids, 1):
            self.wait()
            try:
                r = requests.get(f"https://api.discogs.com/releases/{rid}", headers=headers, timeout=10)
                if r.status_code != 200:
                    self.errors.append(rid)
                    continue
                d = r.json()
                rows.append({
                    "Catalog#": ", ".join(l.get("catno","") for l in d.get("labels",[])),
                    "Discogs ID": rid,
                    "Artist": d["artists"][0]["name"],
                    "Title": d["title"],
                    "Format": d.get("formats",""),
                    "Label": ", ".join(l["name"] for l in d.get("labels",[])),
                    "Released": d.get("released",""),
                    "Genres": "; ".join(d.get("genres",[])),
                    "Styles": "; ".join(d.get("styles",[])),
                    "Import Date": datetime.now().date().isoformat()
                })
            except Exception:
                self.errors.append(rid)
            self.after(0, lambda val=i: self.progress.configure(value=val))

        pd.DataFrame(rows).to_csv(MASTER_CSV, index=False)
        self.after(0, lambda: self.finish("Build complete"))

    def run_update(self):
        threading.Thread(target=self.update_master, daemon=True).start()

    def update_master(self):
        if not os.path.exists(MASTER_CSV):
            return
        shutil.copy2(MASTER_CSV, f"BACKUP_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

        headers = self.get_api_headers()
        df = pd.read_csv(MASTER_CSV)
        df.set_index("Discogs ID", inplace=True)

        self.after(0, lambda: self.progress.configure(maximum=len(df)))

        for i, rid in enumerate(df.index, 1):
            self.wait()
            try:
                r = requests.get(f"https://api.discogs.com/releases/{rid}", headers=headers, timeout=10)
                if r.status_code != 200:
                    self.errors.append(rid)
                    continue
                d = r.json()
                df.at[rid, "Released"] = d.get("released","")
                df.at[rid, "Import Date"] = datetime.now().date().isoformat()
            except Exception:
                self.errors.append(rid)
            self.after(0, lambda val=i: self.progress.configure(value=val))

        df.reset_index().to_csv(MASTER_CSV, index=False)
        self.after(0, lambda: self.finish("Update complete"))

    # ---------- Labels ----------
    def run_labels(self, preview):
        self.save_settings()
        threading.Thread(target=self.labels, args=(preview,), daemon=True).start()

    def labels(self, preview):
        if not os.path.exists(MASTER_CSV):
            self.after(0, lambda: self.finish("CSV not found. Build Master first."))
            return
        
        df = pd.read_csv(MASTER_CSV)
        output = "labels_preview.pdf" if preview else "labels_avery.pdf"
        c = canvas.Canvas(output, pagesize=letter)
        selected_font = self.font_var.get()
        
        idx = int(self.start_label.get()) - 1
        for _, r in df.iterrows():
            col = idx % COLUMNS
            rowp = (idx // COLUMNS) % ROWS
            if idx > 0 and idx % (COLUMNS * ROWS) == 0:
                c.showPage()
                if preview:
                    break

            x = LEFT_MARGIN + col * (LABEL_WIDTH + X_GAP)
            y = PAGE_HEIGHT - TOP_MARGIN - (rowp + 1) * LABEL_HEIGHT

            try:
                c.setFont(f"{selected_font}-Bold", 7)
                c.drawString(x+2, y+LABEL_HEIGHT-10, str(r["Genres"]).split(";")[0])
                c.drawRightString(x+LABEL_WIDTH-2, y+LABEL_HEIGHT-10, str(r["Released"])[:4])

                draw_wrapped_text(c, r["Artist"], x+LABEL_WIDTH/2, y+LABEL_HEIGHT/2+10,
                                  LABEL_WIDTH-10, f"{selected_font}-Bold", 10, 1)
                draw_wrapped_text(c, r["Title"], x+LABEL_WIDTH/2, y+LABEL_HEIGHT/2-2,
                                  LABEL_WIDTH-10, f"{selected_font}-Bold", 8, 2)

                c.setFont(selected_font, 7)
                c.drawString(x+2, y+12, str(r["Label"])[:40])
                c.drawString(x+2, y+4, str(r["Catalog#"])[:30])
                c.drawRightString(x+LABEL_WIDTH-2, y+4,
                                  normalize_fractions(str(r["Format"]))[:32])
            except Exception:
                c.setFont("Helvetica-Bold", 7)
                c.drawString(x+2, y+LABEL_HEIGHT-10, "FONT ERROR")

            idx += 1

        c.save()
        os.startfile(output)  # nosec B606
        self.after(0, lambda: self.finish("Labels created"))

    def finish(self, msg):
        if self.errors:
            messagebox.showwarning("Completed with errors",
                                   f"{msg}\nErrors: {len(self.errors)}")
            self.errors.clear()
        self.status.config(text=msg)

if __name__ == "__main__":
    DiscogsApp().mainloop()