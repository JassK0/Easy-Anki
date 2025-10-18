import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
import os

# Import functions and classes from main.py
from main import load_questions, load_progress, save_progress, choose_exam_set, filter_questions, parse_chapter_filter, CardState, log_event

PROGRESS_FILE = "course_progress.json"
LOG_FILE = "session_log.jsonl"

class QuizGUI:
    def __init__(self, root):
        self.root = root
        root.title("Course Trainer — GUI")
        self.source = None
        self.mode = 'exam'
        self.num = 10
        self.chapters = None
        self.tags = None

        self.all_qs = load_questions(self.source)
        self.prog = load_progress(PROGRESS_FILE)
        self.pool = self.all_qs[:]

        # UI frames
        top = tk.Frame(root)
        top.pack(fill=tk.X, padx=8, pady=6)
        tk.Button(top, text="Load CSV/JSON", command=self.load_file).pack(side=tk.LEFT)
        tk.Button(top, text="Filters", command=self.set_filters).pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="Start", command=self.start_session).pack(side=tk.RIGHT)

        mid = tk.Frame(root)
        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self.prompt_label = tk.Label(mid, text="Click Start to begin", wraplength=700, justify=tk.LEFT)
        self.prompt_label.pack(anchor=tk.W)

        self.opts_vars = []
        self.opts_buttons = []
        for i in range(4):
            var = tk.StringVar(value="")
            btn = tk.Button(mid, textvariable=var, anchor='w', command=lambda i=i: self.answer(i))
            btn.pack(fill=tk.X, pady=2)
            self.opts_vars.append(var)
            self.opts_buttons.append(btn)

        bottom = tk.Frame(root)
        bottom.pack(fill=tk.X, padx=8, pady=6)
        self.status = tk.Label(bottom, text="Ready")
        self.status.pack(side=tk.LEFT)
        tk.Button(bottom, text="Save Progress", command=self.save).pack(side=tk.RIGHT)

        self.current_set = []
        self.current_index = 0
        self.current_question = None
        self.wrong = []

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON/CSV","*.json;*.csv"), ("All","*.*")])
        if not path:
            return
        self.source = path
        self.all_qs = load_questions(path)
        self.pool = self.all_qs[:]
        messagebox.showinfo("Loaded", f"Loaded {len(self.all_qs)} questions from {os.path.basename(path)}")

    def set_filters(self):
        ch = simpledialog.askstring("Chapters", "Enter chapters (e.g. 3,4,9-12) or leave empty:")
        tg = simpledialog.askstring("Tags", "Enter tags (comma separated) or leave empty:")
        self.chapters = parse_chapter_filter(ch)
        self.tags = [t.strip().lower() for t in tg.split(",") if t.strip()] if tg else None
        self.pool = filter_questions(self.all_qs, self.chapters, self.tags)
        messagebox.showinfo("Filters", f"Pool size: {len(self.pool)}")

    def start_session(self):
        if not self.pool:
            messagebox.showerror("No Questions", "Question pool is empty. Load questions or clear filters.")
            return
        self.current_set = choose_exam_set(self.pool, self.num, self.prog)
        self.current_index = 0
        self.wrong = []
        self.next_question()

    def next_question(self):
        if self.current_index >= len(self.current_set):
            if self.wrong:
                self.current_set = self.wrong
                self.wrong = []
                self.current_index = 0
                messagebox.showinfo("Review", "Starting review of missed questions.")
            else:
                messagebox.showinfo("Done", "Session complete. Progress saved.")
                self.save()
                return
        self.current_question = self.current_set[self.current_index]
        q = self.current_question
        self.prompt_label.config(text=f"[{q.id}] {q.prompt}")
        for i, opt in enumerate(q.options):
            self.opts_vars[i].set(f"{chr(ord('A')+i)}) {opt}")
            self.opts_buttons[i].config(state=tk.NORMAL)
        self.status.config(text=f"Question {self.current_index+1}/{len(self.current_set)}")

    def answer(self, idx):
        q = self.current_question
        choice = chr(ord('A')+idx)
        ok = (choice == q.answer)
        if ok:
            messagebox.showinfo("Result","Correct")
            st = self.prog.get(q.id, CardState())
            st.promote()
            self.prog[q.id] = st
        else:
            messagebox.showinfo("Result", f"Incorrect — correct: {q.answer}\n\n{q.explanation}")
            st = self.prog.get(q.id, CardState())
            st.demote()
            self.prog[q.id] = st
            self.wrong.append(q)
        self.current_index += 1
        self.next_question()

    def save(self):
        save_progress(PROGRESS_FILE, self.prog)
        log_event(LOG_FILE, {"mode": self.mode, "count_pool": len(self.pool)})
        messagebox.showinfo("Saved", f"Progress saved to {PROGRESS_FILE}")


if __name__ == '__main__':
    main_root = tk.Tk()
    app = QuizGUI(main_root)
    main_root.mainloop()
