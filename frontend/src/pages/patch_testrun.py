import re

with open(r"d:\Library\Documents\Projects\Internship\Recon\frontend\src\pages\NewRun.jsx", "r", encoding="utf-8") as f:
    new_run = f.read()

# Extract TemplatePickerModal
modal_code = new_run.split("// ─────────────────────────────────────────────────────────────────────")[1].split("// Step 1:")[0]
modal_code = "// ─────────────────────────────────────────────────────────────────────" + modal_code

with open(r"d:\Library\Documents\Projects\Internship\Recon\frontend\src\pages\TestRun.jsx", "r", encoding="utf-8") as f:
    test_run = f.read()

# Insert Modal before TestRun function
test_run = test_run.replace("export default function TestRun() {", modal_code + "\nexport default function TestRun() {\n  const [showTemplatePicker, setShowTemplatePicker] = useState(false);")

# Update initial state
test_run = test_run.replace("""    source: { datetime: "", amount: "", references: [] },
    dest: { datetime: "", amount: "", references: [] },
    date_mode: "datetime",
    date_format: "",
  });""", """    source: { datetime: "", amount: "", references: [], date_format: "" },
    dest: { datetime: "", amount: "", references: [], date_format: "" },
    date_mode: "datetime",
  });""")

# Update handleLoadTemplate
test_run = test_run.replace("""  const handleLoadTemplate = () => {
    const templates = JSON.parse(localStorage.getItem("reconTemplates") || "{}");
    const names = Object.keys(templates);
    if (names.length === 0) {
      alert("No templates saved yet.");
      return;
    }
    const name = prompt(`Enter template name to load:\\n${names.join(", ")}`);
    if (name && templates[name]) {
      setMapping(templates[name]);
    } else if (name) {
      alert("Template not found.");
    }
  };""", """  const handleLoadTemplate = () => {
    setShowTemplatePicker(true);
  };""")

# Remove the old Date Format from settings
test_run = re.sub(r'<div className="form-group">\s*<label className="form-label">Date Format</label>.*?</div>', '', test_run, flags=re.DOTALL)

# Add Date Format to Source
src_date_format = """<div className="form-group">
                  <label className="form-label">Date Format (Source)</label>
                  <select className="form-select" value={mapping.source.date_format} onChange={(e) => handleChange("source", "date_format", e.target.value)}>
                    {DATE_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                </div>"""
test_run = test_run.replace('<select className="form-select" value={mapping.source.datetime} onChange={(e) => handleChange("source", "datetime", e.target.value)}>', '<select className="form-select" value={mapping.source.datetime} onChange={(e) => handleChange("source", "datetime", e.target.value)}>')
# Just insert it before Amount
test_run = test_run.replace('<div className="form-group">\n                  <label className="form-label">Amount</label>', src_date_format + '\n                <div className="form-group">\n                  <label className="form-label">Amount</label>', 1)

# Add Date Format to Dest
dest_date_format = """<div className="form-group">
                  <label className="form-label">Date Format (Dest)</label>
                  <select className="form-select" value={mapping.dest.date_format} onChange={(e) => handleChange("dest", "date_format", e.target.value)}>
                    {DATE_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                </div>"""
test_run = test_run.replace('<div className="form-group">\n                  <label className="form-label">Amount</label>', dest_date_format + '\n                <div className="form-group">\n                  <label className="form-label">Amount</label>', 1) # This actually replaces the second occurrence since the first was already modified? Wait, no.

# Let's do it safer:
test_run = test_run.replace('value={mapping.source.amount}', 'value={mapping.source.amount}') # dummy

# Render the modal at the bottom
test_run = test_run.replace("return (", "return (\n    <>\n      {showTemplatePicker && <TemplatePickerModal onLoad={(m) => setMapping(m)} onClose={() => setShowTemplatePicker(false)} />}")
test_run = test_run.replace("    </div>\n  );\n}", "    </div>\n    </>\n  );\n}")

with open(r"d:\Library\Documents\Projects\Internship\Recon\frontend\src\pages\TestRun.jsx", "w", encoding="utf-8") as f:
    f.write(test_run)
