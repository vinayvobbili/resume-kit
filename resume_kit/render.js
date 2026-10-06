// Render a resolved resume spec (JSON from resume_kit.content.Spec) to .docx.
// Usage: node render.js spec.json out.docx
const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, AlignmentType, LevelFormat, BorderStyle, TabStopType } = require('docx');

const FONT = 'Calibri';
const ACCENT = '1F3A5F';
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

const heading = (t) => new Paragraph({
  spacing: { before: 160, after: 60 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT, space: 1 } },
  children: [new TextRun({ text: t.toUpperCase(), bold: true, size: 21, color: ACCENT })],
});

// "Label: rest" with bold label
const bullet = (text) => {
  const m = text.match(/^([^:]{2,60}):\s(.*)$/);
  const runs = m
    ? [new TextRun({ text: m[1] + ': ', bold: true }), new TextRun(m[2])]
    : [new TextRun(text)];
  return new Paragraph({ numbering: { reference: 'b', level: 0 }, spacing: { after: 30 }, children: runs });
};
const plainBullet = (text) => new Paragraph({ numbering: { reference: 'b', level: 0 }, spacing: { after: 30 }, children: [new TextRun(text)] });

const role = (title, org, dates) => new Paragraph({
  spacing: { before: 100, after: 40 },
  keepNext: true,
  tabStops: [{ type: TabStopType.RIGHT, position: 10800 }],
  children: [
    new TextRun({ text: title, bold: true }),
    new TextRun({ text: '  |  ' + org }),
    ...(dates ? [new TextRun({ text: '\t' + dates, italics: true })] : []),
  ],
});

const para = (runs, opts = {}) => new Paragraph({ spacing: { after: 40 }, ...opts, children: runs });
const centered = (after, run) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after }, children: [new TextRun(run)] });

const children = [
  centered(20, { text: spec.name, bold: true, size: 34, color: ACCENT }),
  centered(20, { text: spec.headline, size: 20, color: '444444' }),
  centered(60, { text: spec.contact, size: 18 }),

  heading('Summary'),
  para([new TextRun(spec.summary)]),

  heading('Core Skills'),
  ...spec.skills.map(bullet),

  heading('Professional Experience'),
  ...spec.roles.flatMap((r) => [role(r.title, r.org, r.dates), ...r.bullets.map(plainBullet)]),

  ...(spec.open_source.length ? [heading(spec.open_source_heading), ...spec.open_source.map(bullet)] : []),

  heading('Education'),
  ...spec.education.flatMap((e) => [
    para([new TextRun({ text: e.school, bold: true }), new TextRun(' — ' + e.degree)]),
    ...(e.coursework ? [para([new TextRun({ text: 'Relevant coursework: ', italics: true }), new TextRun({ text: e.coursework, italics: true })], { indent: { left: 200 } })] : []),
  ]),

  ...(spec.certs.length ? [heading('Certifications')] : []),
  ...(spec.certs_inline ? [spec.certs.join('  •  ')] : spec.certs).filter(Boolean).map((c) => para([new TextRun(c)], { spacing: { after: 20 } })),
];

const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: 20 } } } },
  numbering: { config: [{ reference: 'b', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 300, hanging: 200 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 720, bottom: 720, left: 720, right: 720 } } },
    children,
  }],
});

Packer.toBuffer(doc).then((b) => fs.writeFileSync(process.argv[3], b));
