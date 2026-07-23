"""
Generate watsonxcelerate-pitch.docx
Changes vs previous version:
  - Document header: "AI-Powered IBM Cloud Infrastructure Intelligent Log Analyzer"
  - Removed "Judging Criteria Alignment" section
  - Added chatbot-built-in-5-mins item in "How IBM Bob Was Used"
  - Page 3 subtitle updated
"""

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

# ── Colours ──────────────────────────────────────────────────────────────────
C_DARK    = RGBColor(0x1f, 0x23, 0x28)
C_BLUE    = RGBColor(0x3b, 0x82, 0xd4)
C_PURPLE  = RGBColor(0x7c, 0x5c, 0xd8)
C_GREEN   = RGBColor(0x16, 0xa3, 0x4a)
C_MUTED   = RGBColor(0x57, 0x60, 0x6a)
C_WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
C_SURFACE = RGBColor(0xF7, 0xF8, 0xFA)

doc = Document()

# ── Page setup: Letter, narrow margins ───────────────────────────────────────
section = doc.sections[0]
section.page_width  = Inches(8.5)
section.page_height = Inches(11)
section.left_margin = section.right_margin = Inches(0.85)
section.top_margin  = section.bottom_margin = Inches(0.75)

# ── Helper: shade table cell ─────────────────────────────────────────────────
def shade_cell(cell, hex_color: str):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)

def set_cell_border(cell, **kwargs):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        border = OxmlElement(f"w:{side}")
        border.set(qn("w:val"),   kwargs.get("val",   "single"))
        border.set(qn("w:sz"),    kwargs.get("sz",    "6"))
        border.set(qn("w:space"), "0")
        border.set(qn("w:color"), kwargs.get("color", "E5E7EB"))
        tcBorders.append(border)
    tcPr.append(tcBorders)

# ── Helper: paragraph style ───────────────────────────────────────────────────
def para(doc_or_cell, text="", bold=False, size=11, colour=None, align=WD_ALIGN_PARAGRAPH.LEFT, space_before=0, space_after=4):
    if hasattr(doc_or_cell, "add_paragraph"):
        p = doc_or_cell.add_paragraph()
    else:
        p = doc_or_cell.paragraphs[0] if doc_or_cell.paragraphs else doc_or_cell.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after  = Pt(space_after)
    if text:
        run = p.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        run.font.color.rgb = colour or C_DARK
    return p

def h1(doc_obj, text):
    p = doc_obj.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(4)
    # bottom border
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"),   "single")
    bottom.set(qn("w:sz"),    "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "3B82D4")
    pBdr.append(bottom)
    pPr.append(pBdr)
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = C_BLUE
    return p

def page_header(doc_obj, brand_text, subtitle, badge):
    t = doc_obj.add_table(rows=1, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = "Table Grid"
    # remove all borders
    for row in t.rows:
        for cell in row.cells:
            set_cell_border(cell, val="none", color="FFFFFF")
    lc = t.rows[0].cells[0]
    lc.width = Inches(4.5)
    p1 = lc.paragraphs[0]
    r1 = p1.add_run("WatsonX")
    r1.bold = True; r1.font.size = Pt(18); r1.font.color.rgb = C_DARK
    r2 = p1.add_run("celerate")
    r2.bold = True; r2.font.size = Pt(18); r2.font.color.rgb = C_BLUE
    lc.add_paragraph(brand_text).runs[0].font.color.rgb = C_MUTED if lc.paragraphs else None
    p2 = lc.paragraphs[1] if len(lc.paragraphs) > 1 else lc.add_paragraph()
    if not p2.runs:
        r = p2.add_run(subtitle)
    else:
        r = p2.runs[0]
    r.font.size = Pt(9)
    r.font.color.rgb = C_MUTED

    rc = t.rows[0].cells[1]
    rc.width = Inches(2.3)
    rc.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    shade_cell(rc, "1F2328")
    p3 = rc.paragraphs[0]
    p3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    rr = p3.add_run(badge)
    rr.bold = True; rr.font.size = Pt(8); rr.font.color.rgb = C_WHITE

    # thick bottom border on table via paragraph border below
    doc_obj.add_paragraph()  # spacer

def page_footer(doc_obj, left_text, page_num):
    p = doc_obj.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"),   "single")
    top.set(qn("w:sz"),    "4")
    top.set(qn("w:space"), "1")
    top.set(qn("w:color"), "E5E7EB")
    pBdr.append(top)
    pPr.append(pBdr)
    r1 = p.add_run(left_text)
    r1.font.size = Pt(8); r1.font.color.rgb = C_MUTED
    tab = p.add_run("\t" + page_num)
    tab.font.size = Pt(8); tab.font.color.rgb = C_MUTED
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT

def two_col_surface(doc_obj, left_title, left_lines, right_title, right_lines):
    t = doc_obj.add_table(rows=1, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = "Table Grid"
    for row in t.rows:
        for cell in row.cells:
            shade_cell(cell, "F7F8FA")
            set_cell_border(cell, color="E5E7EB")
    lc = t.rows[0].cells[0]
    rc = t.rows[0].cells[1]
    lc.width = rc.width = Inches(2.9)

    def fill(cell, title, lines):
        p = cell.paragraphs[0]
        r = p.add_run(title)
        r.bold = True; r.font.size = Pt(11); r.font.color.rgb = C_DARK
        for line in lines:
            np = cell.add_paragraph(line)
            np.paragraph_format.space_before = Pt(1)
            np.paragraph_format.space_after  = Pt(1)
            for run in np.runs:
                run.font.size = Pt(10)
                run.font.color.rgb = C_DARK

    fill(lc, left_title,  left_lines)
    fill(rc, right_title, right_lines)
    doc_obj.add_paragraph()

def impact_row(doc_obj, items):
    """items = [(big_text, label), ...]"""
    t = doc_obj.add_table(rows=1, cols=len(items))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = "Table Grid"
    for i, (big, label) in enumerate(items):
        cell = t.rows[0].cells[i]
        shade_cell(cell, "F7F8FA")
        set_cell_border(cell, color="E5E7EB")
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p1 = cell.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rb = p1.add_run(big)
        rb.bold = True; rb.font.size = Pt(22); rb.font.color.rgb = C_BLUE
        p2 = cell.add_paragraph(label)
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p2.runs:
            run.font.size = Pt(9); run.font.color.rgb = C_MUTED
    doc_obj.add_paragraph()

def pipeline_para(doc_obj, steps):
    p = doc_obj.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after  = Pt(8)
    for i, (text, style) in enumerate(steps):
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(9)
        if style == "ai":
            run.font.color.rgb = C_BLUE
        elif style == "out":
            run.font.color.rgb = C_PURPLE
        else:
            run.font.color.rgb = C_DARK
        if i < len(steps) - 1:
            arr = p.add_run("  →  ")
            arr.font.size = Pt(9); arr.font.color.rgb = C_MUTED
    return p

def add_data_table(doc_obj, headers, rows, col_widths=None):
    t = doc_obj.add_table(rows=1 + len(rows), cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = "Table Grid"
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in t.rows:
                row.cells[i].width = Inches(w)
    # header row
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        shade_cell(cell, "1F2328")
        set_cell_border(cell, color="1F2328")
        p = cell.paragraphs[0]
        r = p.add_run(h)
        r.bold = True; r.font.size = Pt(9); r.font.color.rgb = C_WHITE
    # data rows
    for ri, row_data in enumerate(rows):
        fill = "F7F8FA" if ri % 2 == 1 else "FFFFFF"
        for ci, cell_text in enumerate(row_data):
            cell = t.rows[ri + 1].cells[ci]
            shade_cell(cell, fill)
            set_cell_border(cell, color="E5E7EB")
            p = cell.paragraphs[0]
            is_green = isinstance(cell_text, tuple) and cell_text[0] == "green"
            text = cell_text[1] if isinstance(cell_text, tuple) else cell_text
            r = p.add_run(text)
            r.font.size = Pt(9)
            if is_green:
                r.bold = True; r.font.color.rgb = C_GREEN
            else:
                r.font.color.rgb = C_DARK
    doc_obj.add_paragraph()
    return t

# ═════════════════════════════════════════════════════════════════════════════
# PAGE 1
# ═════════════════════════════════════════════════════════════════════════════
page_header(doc,
    "AI-Powered IBM Cloud Infrastructure Intelligent Log Analyzer",
    "AI-Powered IBM Cloud Infrastructure Intelligent Log Analyzer",
    "2026 IBMer watsonx Challenge  •  Path 1 — Built during the challenge")

h1(doc, "The Problem")
p = doc.add_paragraph(
    "Oracle-on-IBM-PowerVS deployments run through IBM Cloud Projects / Schematics generate thousands "
    "of log lines per Terraform run. Every incident forces engineers to manually triage raw output to "
    "find a single root cause — a repetitive, time-consuming task that blocks resolution and requires deep technical expertise.")
p.paragraph_format.space_after = Pt(8)
for run in p.runs: run.font.size = Pt(10)

problem_tbl = doc.add_table(rows=2, cols=2)
problem_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
problem_tbl.style = "Table Grid"
problems = [
    ("45+ min per incident",  "Average time manually reading Terraform logs to identify a root cause"),
    ("Low signal-to-noise",   "Critical errors buried in thousands of verbose Ansible / Terraform lines"),
    ("Skill gap",             "Non-technical team members cannot interpret raw Schematics logs"),
    ("Repetitive triage",     "Same SSH / PowerVS / Ansible error classes appear across every failed run"),
]
for idx, (title, desc) in enumerate(problems):
    row, col = divmod(idx, 2)
    cell = problem_tbl.rows[row].cells[col]
    shade_cell(cell, "FFF5F5")
    set_cell_border(cell, color="FECACA")
    p1 = cell.paragraphs[0]
    rb = p1.add_run(title)
    rb.bold = True; rb.font.size = Pt(10); rb.font.color.rgb = C_DARK
    p2 = cell.add_paragraph(desc)
    for r in p2.runs: r.font.size = Pt(9); r.font.color.rgb = C_MUTED
doc.add_paragraph()

h1(doc, "The Solution")
p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(4)
rb = p.add_run("WatsonXcelerate")
rb.bold = True; rb.font.size = Pt(10); rb.font.color.rgb = C_DARK
rs = p.add_run(
    " automates the full triage pipeline — from log fetch to root-cause report — "
    "using IBM Bob as the development accelerator and ")
rs.font.size = Pt(10); rs.font.color.rgb = C_DARK
rw = p.add_run("watsonx.ai"); rw.bold = True; rw.font.size = Pt(10); rw.font.color.rgb = C_DARK
re = p.add_run(" (Mistral & Granite models) for AI classification and conversational follow-up.")
re.font.size = Pt(10); re.font.color.rgb = C_DARK

pipeline_para(doc, [
    ("Schematics REST API", ""), ("Log Fetch", ""), ("Noise Filter", ""),
    ("Error Blocks", ""), ("watsonx.ai LLM", "ai"), ("Dedup + Root Cause", ""), ("Carbon Dashboard", "out"),
])

two_col_surface(doc,
    "Who Benefits",
    ["On-call engineers — instant root-cause, no log scrolling",
     "Operations managers — trend charts, recurring failure visibility",
     "Non-technical stakeholders — plain-English chatbot answers"],
    "Key Outcomes",
    ["Root cause in ~3 minutes vs. 45+ minutes manually",
     "70% of triage tasks fully automated",
     "~80% of non-technical staff can now act on log results"]
)

h1(doc, "Solution Impact")
impact_row(doc, [
    ("15x",   "Faster root cause\nidentification\n(45 min → 3 min)"),
    ("10x",   "Faster incident\nreport drafting\n(20 min → 2 min)"),
    ("70%",   "Repetitive triage\ntasks fully\nautomated"),
    ("+70pt", "Non-technical staff\nable to interpret\nlogs (10% → 80%)"),
])

page_footer(doc, "WatsonXcelerate  •  2026 IBMer watsonx Challenge", "Page 1 of 3")

# ═════════════════════════════════════════════════════════════════════════════
# PAGE 2
# ═════════════════════════════════════════════════════════════════════════════
doc.add_page_break()
page_header(doc,
    "AI-Powered IBM Cloud Infrastructure Intelligent Log Analyzer",
    "System Architecture & Technical Design",
    "Technical Statement")

h1(doc, "System Architecture")

arch_rows = [
    [("IBM Cloud Schematics\nTerraform Workspaces • us-south / eu / uk", "1F2328", C_WHITE),
     ("→", None, C_MUTED),
     ("Log Ingestion\nfetch_schematics_logs.py", "DBEAFE", RGBColor(0x1d,0x4e,0xd8)),
     ("→", None, C_MUTED),
     ("Pre-Processing\nnormalize • filter • extract", "FFFFFF", C_DARK)],
    [("↓ ↓ ↓", None, C_MUTED), ("", None, C_MUTED), ("", None, C_MUTED), ("", None, C_MUTED), ("", None, C_MUTED)],
    [("Error Blocks\n±30/80 line context", "FFFFFF", C_DARK),
     ("→", None, C_MUTED),
     ("watsonx.ai LLM\nmistral-medium-2505\nGreedy • 800 tokens", "DBEAFE", RGBColor(0x1d,0x4e,0xd8)),
     ("→", None, C_MUTED),
     ("Post-Processing\ndedup • cascade root cause filter", "FFFFFF", C_DARK)],
    [("↓ ↓ ↓", None, C_MUTED), ("", None, C_MUTED), ("", None, C_MUTED), ("", None, C_MUTED), ("", None, C_MUTED)],
    [("dc_scheduled_runs.json\nPersistent structured store", "DCFCE7", RGBColor(0x15,0x80,0x3d)),
     ("→", None, C_MUTED),
     ("IBM Carbon Dashboard\nHome • Runs Table • Analytics", "EDE9FE", RGBColor(0x5b,0x21,0xb6)),
     ("→", None, C_MUTED),
     ("Granite Chatbot\ngranite-3-8b-instruct • SSE streaming", "EDE9FE", RGBColor(0x5b,0x21,0xb6))],
]

arch_tbl = doc.add_table(rows=len(arch_rows), cols=5)
arch_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
arch_tbl.style = "Table Grid"
col_widths_arch = [1.3, 0.25, 1.5, 0.25, 1.5]
for ci, w in enumerate(col_widths_arch):
    for row in arch_tbl.rows:
        row.cells[ci].width = Inches(w)

for ri, row_data in enumerate(arch_rows):
    for ci, (text, fill, color) in enumerate(row_data):
        cell = arch_tbl.rows[ri].cells[ci]
        if fill:
            shade_cell(cell, fill)
        set_cell_border(cell, color="E5E7EB")
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if text:
            r = p.add_run(text)
            r.font.size = Pt(8.5)
            r.font.color.rgb = color
doc.add_paragraph()

proxy_p = doc.add_paragraph("All traffic proxied via proxy.py (localhost:8080) — CORS-safe IAM token exchange + watsonx.ai streaming")
proxy_p.paragraph_format.space_after = Pt(8)
for r in proxy_p.runs: r.font.size = Pt(9); r.font.color.rgb = C_MUTED

h1(doc, "7-Stage Error Classification Pipeline")
add_data_table(doc,
    ["#", "Stage", "Implementation", "What it does"],
    [
        ["1", "Normalization",       "normalize_log_line()",              "Strip ANSI codes, decode HTML entities, remove Schematics timestamp prefixes"],
        ["2", "Noise Filtering",     "_is_noise_line()",                  "50+ compiled regex patterns — drops Terraform progress, Ansible ok/skip, warnings"],
        ["3", "Error Anchor Detect", "_is_error_line()",                  "Matches Error:, HTTP 4xx/5xx, provider failures, SSH errors, Python exceptions"],
        ["4", "Block Extraction",    "extract_error_blocks()",            "30 lines before + 80 lines after each anchor; merges overlapping windows (≤15 line gap)"],
        ["5", "Wrapper Filter",      "filter_generic_schematics_blocks()","Drops generic 'SCHEMATICS DEPLOYMENT FAILED' wrappers when specific root-cause blocks exist"],
        ["6", "LLM Classification",  "extract_multiple_errors()",         "Each block sent to mistral-medium-2505; returns JSON [{category, module}]; hardened JSON repair"],
        ["7", "Post-Processing",     "select_root_causes()",              "Validate, deduplicate, cascade suppression (SSH failure drops Ansible / Remote Exec automatically)"],
    ],
    col_widths=[0.2, 1.0, 1.8, 3.3]
)

h1(doc, "24-Category Error Taxonomy")
categories = [
    "SSH Connectivity", "PowerVS Instance", "PowerVS Volume", "PowerVS Network", "PowerVS Workspace",
    "Ansible", "Remote Exec", "Package Install", "IAM / Trusted Profile", "IBM Cloud API",
    "Terraform Apply", "Provider Inconsistency", "VPN", "Load Balancer", "DNS",
    "SSH Key", "Image Import", "Service Connectivity", "Schematics Apply", "Schematics Job",
    "Schematics Workspace", "Deprecated Action / Dependency", "Subscription / Licensing", "Conflict / Already Exists"
]
cat_p = doc.add_paragraph("  •  ".join(categories))
cat_p.paragraph_format.space_after = Pt(8)
for r in cat_p.runs: r.font.size = Pt(9); r.font.color.rgb = C_DARK

h1(doc, "Tech Stack")
add_data_table(doc,
    ["Layer", "Technology", "Notes"],
    [
        ["AI / LLM (Classification)", "watsonx.ai — mistralai/mistral-medium-2505", "Greedy decoding, max 800 tokens/block"],
        ["AI / LLM (Chatbot)",        "watsonx.ai — ibm/granite-3-8b-instruct",     "Streaming chat, SSE"],
        ["Development Assistant",     "IBM Bob",                                     "Scaffolding, prompts, docs, code review"],
        ["IBM Cloud Infrastructure",  "IBM Cloud Schematics REST API v1",            "Terraform workspace execution engine"],
        ["Backend Pipeline",          "Python 3.10+",                                "requests, ibm_watson_machine_learning"],
        ["Frontend",                  "IBM Carbon Design System v10.58",             "Vanilla JS, no bundler"],
        ["Local Dev Server",          "Python http.server (proxy.py)",               "CORS proxy, chunked streaming"],
    ],
    col_widths=[1.6, 2.3, 2.4]
)

page_footer(doc, "WatsonXcelerate  •  2026 IBMer watsonx Challenge", "Page 2 of 3")

# ═════════════════════════════════════════════════════════════════════════════
# PAGE 3
# ═════════════════════════════════════════════════════════════════════════════
doc.add_page_break()
page_header(doc,
    "AI-Powered IBM Cloud Infrastructure Intelligent Log Analyzer",
    "IBM Bob Usage, Solution Statement & Impact",
    "Challenge Alignment & Impact")

h1(doc, "How IBM Bob Was Used")
intro = doc.add_paragraph(
    "IBM Bob was an active collaborator across every stage of the development lifecycle — "
    "not just documentation. Below are concrete examples of Bob's contribution:")
intro.paragraph_format.space_after = Pt(6)
for r in intro.runs: r.font.size = Pt(10)

bob_items = [
    ("Scaffolding",
     "Bob generated the initial project structure, directory layout, Python module skeletons, and "
     "requirements.txt — saving ~2 hours of setup boilerplate."),
    ("Pipeline Code",
     "The 7-stage log classification pipeline in fetch_dc_scheduled_runs_logs.py was co-developed with Bob: "
     "noise filter regex patterns, error anchor detection logic, and the sliding window block extractor were "
     "all Bob-generated and iteratively refined."),
    ("Prompt Engineering",
     "Bob drafted and iterated the 2-phase LLM prompt in prompts/prototypev1_terraform_log_analysis.md, "
     "including strict category guide injection, JSON-only output constraints, and cascade suppression rules."),
    ("SDK Wrapper",
     "The WatsonXClient class in utils/watsonx_client.py — typed exception hierarchy, retry logic, and "
     "template loader — was scaffolded by Bob and reviewed for edge cases."),
    ("Chatbot (built in 5 minutes with Bob)",
     "Bob built the full watsonx.ai-powered chatbot panel — CSS floating panel, streaming SSE client in "
     "assets/js/chatbot.js, IAM token caching (55-min TTL), full conversation history management, and "
     "system prompt — from a single natural-language request in under 5 minutes."),
    ("Frontend Dashboard",
     "Bob built the IBM Carbon Design System dashboard pages (Home, Runs Table, Analytics) including "
     "the chart renderer and navigation sidebar — no UI framework or bundler required."),
    ("JSON Hardening",
     "Bob wrote _extract_first_json_array() with markdown fence stripping, bracket-depth extraction, "
     "conservative JSON repair, and regex fallback — covering all LLM output edge cases."),
    ("Documentation",
     "Full technical docs, README, CLI reference (Steps-to-fetch-logs-ibmcli), and this pitch document "
     "were drafted by Bob and human-reviewed for accuracy."),
]

bob_tbl = doc.add_table(rows=len(bob_items), cols=2)
bob_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
bob_tbl.style = "Table Grid"
bob_tbl.columns[0].width = Inches(1.5)
bob_tbl.columns[1].width = Inches(5.1)
for ri, (tag, desc) in enumerate(bob_items):
    fill = "F0F6FF" if ri % 2 == 0 else "FFFFFF"
    tag_cell = bob_tbl.rows[ri].cells[0]
    desc_cell = bob_tbl.rows[ri].cells[1]
    shade_cell(tag_cell, "DBEAFE")
    shade_cell(desc_cell, fill)
    set_cell_border(tag_cell,  color="BFDBFE")
    set_cell_border(desc_cell, color="E5E7EB")
    tag_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    pt = tag_cell.paragraphs[0]
    pt.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = pt.add_run(tag)
    rt.bold = True; rt.font.size = Pt(9); rt.font.color.rgb = RGBColor(0x1d,0x4e,0xd8)
    pd = desc_cell.paragraphs[0]
    rd = pd.add_run(desc)
    rd.font.size = Pt(9); rd.font.color.rgb = C_DARK
doc.add_paragraph()

h1(doc, "Solution Statement  (ready to submit — ~140 words)")
stmt_tbl = doc.add_table(rows=1, cols=1)
stmt_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
stmt_tbl.style = "Table Grid"
sc = stmt_tbl.rows[0].cells[0]
shade_cell(sc, "F7F8FA")
set_cell_border(sc, color="3B82D4", val="single", sz="8")
sc.width = Inches(6.8)
stmt_text = (
    "WatsonXcelerate is an AI-powered log analysis platform for IBM Cloud infrastructure operations. "
    "It targets on-call engineers and operations teams managing Oracle-on-IBM-PowerVS deployments via "
    "IBM Cloud Schematics, where Terraform failures currently require 45+ minutes of manual log triage per incident.\n\n"
    "The solution automatically fetches logs from the Schematics REST API, filters noise using 50+ regex patterns, "
    "extracts focused error blocks, and sends each block to watsonx.ai for classification into a 24-category taxonomy. "
    "Results appear on a live IBM Carbon dashboard with an embedded Granite-powered chatbot — built entirely by IBM Bob "
    "in under 5 minutes — for conversational follow-up.\n\n"
    "Outcomes: root-cause identification drops from ~45 min to ~3 min (15x); 70% of repetitive triage tasks automated; "
    "non-technical staff able to interpret incidents rises from 10% to 80%. IBM Bob was used throughout — scaffolding, "
    "pipeline code, prompt engineering, frontend, chatbot, and documentation."
)
p_stmt = sc.paragraphs[0]
r_stmt = p_stmt.add_run(stmt_text)
r_stmt.font.size = Pt(9.5); r_stmt.font.color.rgb = C_DARK
doc.add_paragraph()

h1(doc, "Impact Estimate")
add_data_table(doc,
    ["Metric", "Before", "After (with WatsonXcelerate)", "Impact Category"],
    [
        ["Root cause identification time", "45 min",   ("green", "3 min"),  "Reduce time to complete routine tasks"],
        ["Incident report drafting",       "20 min",   ("green", "2 min"),  "Reduce time to complete routine tasks"],
        ["Repetitive triage automated",    "0%",        ("green", "70%"),   "Improve accuracy and consistency"],
        ["Non-technical staff can act",    "10%",       ("green", "80%"),   "Reduce operational risk / ensure compliance"],
        ["Task frequency",                 "Multiple times/week per workspace", ("green", "Automated"), "Speed up product/offering development"],
    ],
    col_widths=[1.8, 0.8, 1.6, 2.5]
)

p_note = doc.add_paragraph(
    "Estimated ~45% overall team productivity improvement for on-call and operations team members — "
    "consistent with the average gain IBMers report from using IBM Bob.")
p_note.paragraph_format.space_before = Pt(0)
p_note.paragraph_format.space_after  = Pt(10)
for r in p_note.runs:
    r.bold = True; r.font.size = Pt(10); r.font.color.rgb = C_DARK

page_footer(doc,
    "WatsonXcelerate  •  2026 IBMer watsonx Challenge  •  Naved Afroz",
    "Page 3 of 3")

# ── Made with IBM Bob footer ──────────────────────────────────────────────────
doc.add_paragraph()
f_p = doc.add_paragraph("Made with IBM Bob")
f_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
for r in f_p.runs:
    r.font.size = Pt(9); r.font.color.rgb = C_MUTED

# ── Save ──────────────────────────────────────────────────────────────────────
out = "doc/watsonxcelerate-pitch.docx"
doc.save(out)
print(f"Saved: {out}")
