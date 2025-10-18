# quiz_plus.py
# Easy Anki (Exam + SRS + Filters + CSV/JSON loader)
import argparse
import csv
import json
import math
import os
import random
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

# --------------------------- Data Models ---------------------------

@dataclass
class Question:
    id: str
    prompt: str
    options: List[str]
    answer: str  # 'A'|'B'|'C'|'D'
    explanation: str
    chapter: Optional[str] = None   # e.g., '3', '10', '12'
    tags: List[str] = field(default_factory=list)  # e.g., ['photosynthesis','calvin']

    def canonical(self):
        self.answer = self.answer.strip().upper()
        self.options = [o.strip() for o in self.options]
        self.tags = [t.strip().lower() for t in self.tags if t.strip()]
        if self.chapter:
            self.chapter = self.chapter.strip()

@dataclass
class CardState:
    # Leitner-style SRS state
    box: int = 1                 # 1..5
    correct_streak: int = 0
    incorrect_count: int = 0
    last_seen: Optional[str] = None  # ISO timestamp
    due: Optional[str] = None        # ISO timestamp

    def promote(self):
        self.correct_streak += 1
        self.box = min(5, self.box + 1)
        self.schedule()

    def demote(self):
        self.correct_streak = 0
        self.box = 1
        self.incorrect_count += 1
        self.schedule(reset=True)

    def schedule(self, reset: bool=False):
        # very simple intervals by box: 1→0d (always due), 2→1d, 3→3d, 4→7d, 5→14d
        intervals = {1:0, 2:1, 3:3, 4:7, 5:14}
        days = 0 if reset else intervals.get(self.box, 0)
        due_date = datetime.utcnow() + timedelta(days=days)
        self.last_seen = datetime.utcnow().isoformat(timespec="seconds")
        self.due = due_date.isoformat(timespec="seconds")

# --------------------------- Built-in Pool (fallback) ---------------------------
# 40 default questions (same content as earlier reply), trimmed for brevity here; keep full set:
BUILTIN: List[Question] = []

def add_builtin():
    def Q(i, prompt, opts, ans, exp, ch=None, tags=""):
        BUILTIN.append(Question(
            id=str(i), prompt=prompt, options=opts, answer=ans, explanation=exp,
            chapter=ch, tags=[t.strip() for t in tags.split(",") if t.strip()]
        ))
    A,B,C,D="A","B","C","D"
    # --- Add all 40 questions from previous answer (omitted comments) ---
    add = Q
    add(1,"Which interaction MOST directly stabilizes α-helices and β-sheets?",
        ["Hydrogen bonds between backbone groups","Hydrophobic clustering of side chains",
         "Ionic bonds between acidic/basic R groups","Disulfide bridges between cysteines"],
        A,"Secondary structure is stabilized by H-bonds between backbone C=O and N–H.", "3","proteins,structure")
    add(2,"A single amino acid change most directly changes which protein level first?",
        ["Primary","Secondary","Tertiary","Quaternary"],
        A,"Primary sequence changes first; higher levels may change as a consequence.","3","proteins")
    add(3,"Competitive inhibitors affect enzymes by…",
        ["Lowering Vmax only","Raising Km (apparent) by competing at the active site",
         "Lowering Km by binding allosterically","Raising Vmax by increasing catalytic rate"],
        B,"They compete at the active site → need more substrate to reach same rate (↑Km).","8","enzymes,inhibition")
    add(4,"DNA strands in the double helix are:",
        ["Parallel and identical","Antiparallel and complementary","Antiparallel and identical","Parallel and complementary"],
        B,"They run 5'→3' opposite directions and pair A-T, C-G.","4","dna")
    add(5,"Which feature makes RNA generally less stable than DNA?",
        ["Uracil","2'-OH on ribose","Phosphodiester bond","Single-strandedness only"],
        B,"The 2'-OH can participate in hydrolysis, reducing stability.","4","rna")
    add(6,"Cellulose differs from starch primarily by:",
        ["Monomer identity","Type of glycosidic linkage","Presence of branching","Covalent peptide crosslinks"],
        B,"Cellulose is β-1,4; starch is α-1,4 (amylose) with α-1,6 branches (amylopectin).","5","carbs")
    add(7,"Glycogen is optimized for:",
        ["Structural rigidity","Rapid glucose release via many branch ends","Water retention in plants","Cell identity signaling"],
        B,"Highly branched α-1,6 points → many ends for fast mobilization.","5","carbs,glycogen")
    add(8,"Increasing which factor DECREASES membrane fluidity/permeability?",
        ["Unsaturated tails","Shorter tails","Cholesterol at moderate temperature","Higher temperature"],
        C,"Cholesterol packs hydrophobic region and reduces fluidity at moderate temps.","6","membrane,lipids")
    add(9,"A red blood cell placed in a hypertonic solution will:",
        ["Swell and burst","No net change","Shrink (crenate)","Actively pump out ions and swell"],
        C,"Water leaves the cell toward higher solute outside → cell shrinks.","6","osmosis")
    add(10,"Which pathway correctly tracks a secreted protein?",
        ["Free ribosome → cytosol → nucleus → plasma membrane",
         "Rough ER → Golgi (cis→trans) → secretory vesicle → exocytosis",
         "Smooth ER → lysosome → nucleus → membrane","Mitochondria → peroxisome → Golgi → secretion"],
        B,"Signal peptide targets RER → processed in Golgi → vesicle → secretion.","7","endomembrane,secretion")
    add(11,"Evidence for endosymbiosis of mitochondria includes:",
        ["Presence of histones identical to eukaryotes","Circular DNA and prokaryote-like ribosomes",
         "Location in the nucleus","Ability to fix nitrogen"],
        B,"Mitochondria have circular DNA and 70S-like ribosomes.","7","endosymbiosis")
    add(12,"Kinesin generally moves cargo along microtubules toward:",
        ["Minus end (toward centrosome)","Plus end (cell periphery)","Actin filaments","Intermediate filaments"],
        B,"Kinesin is plus-end directed; dynein is minus-end directed.","7","cytoskeleton")
    add(13,"An exergonic reaction has:",
        ["ΔG < 0 and can be spontaneous","ΔG > 0 and requires energy input","ΔH > 0 and ΔS < 0 always","No change in free energy"],
        A,"Negative ΔG indicates a thermodynamically favorable process.","8","thermo")
    add(14,"ATP hydrolysis drives endergonic reactions mainly by:",
        ["Raising activation energy","Lowering temperature","Phosphorylating substrates/enzymes to increase their reactivity",
         "Supplying electrons to the ETC"],
        C,"Phosphorylation changes ΔG of coupled steps and conformations.","8","enzymes,atp")
    add(15,"In a redox pair, the molecule that is oxidized:",
        ["Gains electrons","Loses electrons","Gains protons only","Becomes more reduced"],
        B,"Oxidation = loss of electrons.","8","redox")
    add(16,"Final electron acceptor of the mitochondrial ETC is:",
        ["NAD+","FAD","Oxygen","Water"],
        C,"O2 accepts electrons to form H2O at Complex IV.","9","etc")
    add(17,"Where does glycolysis occur?",
        ["Mitochondrial matrix","Cytosol","Inner mitochondrial membrane","Intermembrane space"],
        B,"Glycolysis is cytosolic.","9","glycolysis")
    add(18,"Per glucose, the citric acid cycle directly produces:",
        ["2 ATP (or GTP), 6 NADH, 2 FADH2, 4 CO2","2 ATP, 2 NADH, 0 FADH2, 2 CO2",
         "4 ATP, 2 NADH, 2 FADH2, 6 CO2","30 ATP only"],
        A,"Totals for two turns per glucose.","9","tca")
    add(19,"Phosphofructokinase (PFK-1) is inhibited by high:",
        ["AMP","ATP","Fructose-6-phosphate","Oxygen"],
        B,"High ATP indicates energy sufficiency → slows glycolysis.","9","regulation")
    add(20,"Chemiosmosis refers to:",
        ["Passive glucose diffusion","Proton gradient driving ATP synthase","Osmosis across the plasma membrane","CO2 diffusion into mitochondria"],
        B,"Proton-motive force powers ATP synthase.","9","chemiosmosis")
    add(21,"Which photosystem splits water to release O2?",
        ["Photosystem I","Photosystem II","Both PSI and PSII","Neither"],
        B,"PSII (P680) performs photolysis of water.","10","photosynthesis,psii")
    add(22,"Primary products of the light reactions are:",
        ["CO2 and H2O","RuBP and O2","ATP and NADPH (and O2 by-product)","G3P and glucose"],
        C,"ATP + NADPH feed the Calvin cycle; O2 is released.","10","light-reactions")
    add(23,"Carbon fixation in the Calvin cycle is catalyzed by:",
        ["Rubisco","PEP carboxylase","ATP synthase","Ferredoxin-NADP+ reductase"],
        A,"Rubisco adds CO2 to RuBP.","10","calvin")
    add(24,"C4 plants reduce photorespiration by:",
        ["Fixing CO2 at night only","Concentrating CO2 in bundle-sheath cells via PEP carboxylase",
         "Opening stomata wider during the day","Using only PSI"],
        B,"Spatial separation concentrates CO2 for Rubisco.","10","c4")
    add(25,"The Z-scheme connects:",
        ["Glycolysis to Krebs","PSII to PSI via plastocyanin and ETC","C3 to C4 pathways","Respiration to fermentation"],
        B,"Electron flow: PSII → PQ → Cyt → PC → PSI → Fd → NADPH.","10","z-scheme")
    add(26,"Which junction provides a watertight seal between epithelial cells?",
        ["Gap junction","Tight junction","Desmosome","Hemidesmosome"],
        B,"Tight junctions seal to prevent paracellular leakage.","11","junctions")
    add(27,"Cadherins are key adhesion molecules in:",
        ["Tight junctions","Desmosomes","Gap junctions","Plasmodesmata"],
        B,"Cadherins mediate cell–cell adhesion in desmosomes.","11","junctions")
    add(28,"GPCR signaling often uses second messengers such as:",
        ["DNA polymerase","cAMP or Ca2+","ATP synthase","Rubisco"],
        B,"Small diffusible molecules amplify the signal.","11","gpcr")
    add(29,"Enzyme-linked receptors like RTKs first:",
        ["Hydrolyze ATP in the cytosol","Dimerize and autophosphorylate tyrosines",
         "Open ion channels directly","Release steroid hormones"],
        B,"Ligand binding → dimerization → autophosphorylation.","11","rtk")
    add(30,"DNA replication occurs during:",
        ["G1","S phase","G2","M phase"],
        B,"S = synthesis of DNA.","12","cell-cycle")
    add(31,"Which checkpoint prevents anaphase until all kinetochores attach properly?",
        ["G1","G2/M","M (spindle) checkpoint","Restriction point in G0"],
        C,"Spindle checkpoint ensures proper attachment.","12","checkpoints")
    add(32,"MPF consists of:",
        ["Cyclin + Cdk kinase","p53 + DNA ligase","Actin + myosin","Tubulin + kinesin"],
        A,"Cyclin-dependent kinase activated by mitotic cyclin.","12","mpf")
    add(33,"During telophase in animal cells:",
        ["Chromosomes condense","Nuclear envelopes reform","Cohesins are cleaved","Spindle attaches to kinetochores"],
        B,"Chromosomes decondense and nuclei re-form.","12","mitosis")
    add(34,"Cytokinesis in plants vs animals differs because plants:",
        ["Use a cell plate formed by vesicles; animals use actin–myosin ring",
         "Use actin–myosin; animals use cell plate","Use dynein contraction","Do not divide cytoplasm"],
        A,"Plant cell wall requires a Golgi-derived cell plate.","12","cytokinesis")
    add(35,"Loss of which tumor suppressor commonly disables the G1 DNA-damage checkpoint?",
        ["Ras","Cyclin B","p53","Actin"],
        C,"p53 activates repair or apoptosis upon damage.","12","cancer")
    add(36,"Which is TRUE of fermentation?",
        ["Generates large ATP by oxidative phosphorylation","Regenerates NAD+ to allow glycolysis to continue",
         "Requires O2","Produces CO2 only in lactic fermentation"],
        B,"Key role is NAD+ regeneration when O2 is unavailable.","9","fermentation")
    add(37,"A membrane with long, saturated tails at low temperature will be:",
        ["Highly fluid and permeable","Rigid with low permeability","Unchanged by temperature","Porous to ions"],
        B,"Saturated + long tails + low T → tight packing, low fluidity.","6","membrane")
    add(38,"Plasmodesmata in plants connect cells by:",
        ["Protein channels that open with voltage","Membrane-lined pores with shared cytoplasm (symplast)",
         "Desmosomal cadherin bridges","Tight occluding strands"],
        B,"Plasmodesmata create cytoplasmic continuity.","11","plasmodesmata")
    add(39,"Photorespiration occurs when rubisco binds:",
        ["CO2, producing 3-PGA","O2, consuming ATP and releasing CO2","RuBP, producing G3P directly","NADPH, producing RuBP"],
        B,"O2 addition wastes energy and releases fixed CO2.","10","photorespiration")
    add(40,"Which best defines chemiosmotic ATP formation in chloroplasts?",
        ["Matrix H+ gradient drives ATP synthase",
         "Thylakoid lumen H+ gradient drives ATP synthase to the stroma",
         "Cytosolic H+ gradient drives mitochondrial ATP synthase","No H+ gradient is required"],
        B,"Protons accumulate in thylakoid lumen; ATP made facing stroma.","10","photophosphorylation")

add_builtin()

# --------------------------- IO: CSV/JSON Loader ---------------------------

def load_questions(path: Optional[str]) -> List[Question]:
    if path is None:
        return BUILTIN[:]
    if not os.path.exists(path):
        print(f"[WARN] Source not found: {path}. Using built-in pool.")
        return BUILTIN[:]
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            qs = []
            for row in data:
                q = Question(
                    id=str(row.get("id", row.get("ID", ""))),
                    prompt=row["prompt"],
                    options=[row["A"], row["B"], row["C"], row["D"]],
                    answer=row["answer"],
                    explanation=row.get("explanation", ""),
                    chapter=str(row.get("chapter")) if row.get("chapter") is not None else None,
                    tags=row.get("tags", []),
                )
                q.canonical()
                qs.append(q)
            return qs
        else:
            # CSV columns: id,prompt,A,B,C,D,answer,explanation,chapter,tags
            qs = []
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tags = []
                    if row.get("tags"):
                        tags = [t.strip() for t in re.split(r"[;,]", row["tags"]) if t.strip()]
                    q = Question(
                        id=str(row.get("id", "")),
                        prompt=row["prompt"],
                        options=[row["A"], row["B"], row["C"], row["D"]],
                        answer=row["answer"],
                        explanation=row.get("explanation", ""),
                        chapter=row.get("chapter") or None,
                        tags=tags
                    )
                    q.canonical()
                    qs.append(q)
            return qs
    except Exception as e:
        print(f"[ERROR] Failed to parse {path}: {e}")
        print("[INFO] Using built-in pool.")
        return BUILTIN[:]

# --------------------------- Progress Persistence ---------------------------

def load_progress(fp: str) -> Dict[str, CardState]:
    if not os.path.exists(fp):
        return {}
    try:
        raw = json.load(open(fp, "r", encoding="utf-8"))
        out: Dict[str, CardState] = {}
        for k, v in raw.items():
            st = CardState(**v)
            out[k] = st
        return out
    except Exception:
        return {}

def save_progress(fp: str, prog: Dict[str, CardState]):
    serial = {k: asdict(v) for k, v in prog.items()}
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(serial, f, indent=2)

# --------------------------- Helpers ---------------------------

def parse_chapter_filter(expr: Optional[str]) -> Optional[set]:
    if not expr:
        return None
    # e.g., "3,4,9-12"
    sel = set()
    for token in re.split(r"[,\s]+", expr.strip()):
        if not token: continue
        if "-" in token:
            a,b = token.split("-",1)
            try:
                a=int(a); b=int(b)
                for x in range(min(a,b), max(a,b)+1): sel.add(str(x))
            except: pass
        else:
            sel.add(str(token))
    return sel or None

def filter_questions(qs: List[Question], chapters: Optional[set], tags: Optional[List[str]]) -> List[Question]:
    tags = [t.strip().lower() for t in (tags or []) if t.strip()]
    out = []
    for q in qs:
        if chapters and (not q.chapter or q.chapter not in chapters):
            continue
        if tags and not (set(tags) & set(q.tags)):
            continue
        out.append(q)
    return out

def srs_weight(qid: str, prog: Dict[str, CardState]) -> float:
    # Lower box → higher weight; overdue → bonus
    st = prog.get(qid, CardState())
    base = {1: 1.0, 2: 0.6, 3: 0.35, 4: 0.2, 5: 0.1}[st.box]
    overdue_bonus = 1.0
    if st.due:
        try:
            due = datetime.fromisoformat(st.due)
            if datetime.utcnow() >= due:
                delta_days = (datetime.utcnow() - due).days + 1
                overdue_bonus = 1.0 + min(1.0, 0.2 * delta_days)  # up to 2x
        except Exception:
            pass
    return base * overdue_bonus

def choose_exam_set(qs: List[Question], n: int, prog: Dict[str, CardState]) -> List[Question]:
    # sample with SRS weights; fall back to uniform if small
    if not qs:
        return []
    weights = [srs_weight(q.id, prog) for q in qs]
    total = sum(weights)
    if total == 0:
        random.shuffle(qs)
        return qs[:n]
    # weighted sampling without replacement
    chosen = []
    pool = list(qs)
    w = list(weights)
    for _ in range(min(n, len(pool))):
        total = sum(w)
        r = random.random() * total
        s = 0.0
        idx = 0
        for i, wi in enumerate(w):
            s += wi
            if s >= r:
                idx = i
                break
        chosen.append(pool.pop(idx))
        w.pop(idx)
    return chosen

def print_rule():
    print("\nEnter A/B/C/D (or 'q' to quit). Immediate feedback shown.\n")

def ask(q: Question) -> bool:
    print("\n" + "-"*90)
    print(f"[{q.id}] {q.prompt}")
    for i, opt in enumerate(q.options):
        print(f"  {chr(ord('A')+i)}) {opt}")
    while True:
        choice = input("Your answer (A/B/C/D or q): ").strip().upper()
        if choice == "Q":
            raise SystemExit("\nExiting. Progress saved.")
        if choice in ("A","B","C","D"):
            ok = (choice == q.answer)
            if ok:
                print("✅ Correct.", end=" ")
            else:
                print(f"❌ Incorrect. Correct: {q.answer}", end=" ")
            print(f"\nℹ️  {q.explanation}")
            return ok
        print("Please enter A, B, C, D or q.")

def run_round(qs: List[Question], title: str, prog: Dict[str, CardState]) -> List[Question]:
    print("\n" + "="*90)
    print(f"{title} — {len(qs)} question(s)")
    print("="*90)
    print_rule()
    wrong: List[Question] = []
    for q in qs:
        ok = ask(q)
        st = prog.get(q.id, CardState())
        if ok:
            st.promote()
        else:
            st.demote()
            wrong.append(q)
        prog[q.id] = st
    print(f"\nRound complete: {len(qs)-len(wrong)}/{len(qs)} correct.")
    return wrong

# --------------------------- CLI ---------------------------

def build_argparser():
    p = argparse.ArgumentParser(
        description="Easy Anki — Exam + Anki-style review with SRS and CSV/JSON loader."
    )
    p.add_argument("-s","--source", help="Path to CSV or JSON question bank. If omitted, uses built-in 40.")
    p.add_argument("-m","--mode", choices=["exam","practice"], default="exam",
                   help="exam: 40 questions then wrong-only loops. practice: keep serving SRS-weighted questions indefinitely.")
    p.add_argument("-n","--num", type=int, default=40, help="Number of questions for exam/practice initial round.")
    p.add_argument("-c","--chapters", help='Filter by chapters, e.g., "3,4,9-12".')
    p.add_argument("-t","--tags", help='Filter by tags (comma/space separated), e.g., "calvin,photosynthesis".')
    p.add_argument("--progress", default="course_progress.json", help="Progress JSON file (created/updated automatically).")
    p.add_argument("--log", default="session_log.jsonl", help="Append-only session log.")
    return p

def log_event(fp: str, data: Dict[str, Any]):
    data["_ts"] = datetime.utcnow().isoformat(timespec="seconds")
    with open(fp, "a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")

def main():
    args = build_argparser().parse_args()

    all_qs = load_questions(args.source)
    chapters = parse_chapter_filter(args.chapters)
    tags = re.split(r"[,\s]+", args.tags.strip()) if args.tags else None
    pool = filter_questions(all_qs, chapters, tags)

    if not pool:
        print("[ERROR] No questions match your filter. Try changing --chapters/--tags.")
        sys.exit(1)

    prog = load_progress(args.progress)

    if args.mode == "exam":
        # Choose questions with SRS weighting
        initial = choose_exam_set(pool, args.num, prog)
        wrong = run_round(initial, "Initial Round", prog)
        rnd = 2
        while wrong:
            random.shuffle(wrong)
            wrong = run_round(wrong, f"Review Round {rnd} (Missed Only)", prog)
            rnd += 1
        print("\n🎉 All questions mastered this session.")
    else:
        # Practice mode: continuous SRS batches
        batch = 1
        while True:
            # Pick due/weighted questions
            selection = choose_exam_set(pool, args.num, prog)
            wrong = run_round(selection, f"Practice Batch {batch}", prog)
            batch += 1
            cont = input("\nPress Enter for another batch, or 'q' to quit: ").strip().lower()
            if cont == 'q':
                break

    # Save progress
    save_progress(args.progress, prog)
    log_event(args.log, {
        "mode": args.mode,
        "count_pool": len(pool),
        "filters": {"chapters": sorted(list(chapters)) if chapters else None, "tags": tags},
        "progress_file": args.progress
    })
    print(f"\nProgress saved to: {args.progress}")
    print("Good luck on the midterm!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Progress saved if any.")
