#!/usr/bin/env node
/**
 * Render a lineup JSON (from lineup_doc.py) into a .docx grouped by age group.
 *
 * Order: all boys age groups (8U -> 9-10 -> 11-12 -> 13-14 -> 15-18), each
 * with free/back/breast/fly individual events followed by the age-group relay.
 * Then mixed-age boys relay. Then all girls age groups in the same order.
 * Then mixed-age girls relay. Finally, projected score (vs mode only).
 *
 * Usage: cat lineup.json | node _lineup_doc.js out.docx
 */
const fs = require("fs");
const {
  AlignmentType,
  BorderStyle,
  Document,
  HeadingLevel,
  PageBreak,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} = require("docx");

const STROKE_ORDER = ["FREE", "BACK", "BREAST", "FLY"];
const AGE_ORDER = ["8U", "9-10", "11-12", "13-14", "15-18"];

const PAGE_W = 12240;
const PAGE_H = 15840;
const CONTENT_W = 9360;

function fmtTime(t) {
  if (t == null || isNaN(t)) return "";
  if (t >= 60) {
    const m = Math.floor(t / 60);
    const s = t - m * 60;
    return `${m}:${s.toFixed(2).padStart(5, "0")}`;
  }
  return t.toFixed(2);
}

function ageGenderLabel(ag, gen) {
  const g = gen === "B" ? "Boys" : "Girls";
  if (ag === "8U") return `8 & Under ${g}`;
  if (ag === "15-18") return `15-18 ${g}`;
  return `${ag} ${g}`;
}

function strokeLabel(st) {
  return { FREE: "Free", BACK: "Back", BREAST: "Breast", FLY: "Fly" }[st] || st;
}

function distanceForEvent(ag, st) {
  if (ag === "8U") return 25;
  if (ag === "9-10" && st === "FLY") return 25;
  return 50;
}

function eventTitle(ag, st) {
  return `${distanceForEvent(ag, st)} ${strokeLabel(st)}`;
}

function relayTitle(ag) {
  if (ag === "8U") return "100m Free Relay (4x25)";
  if (ag === "15-18") return "200m Medley Relay (4x50)";
  return "100m Medley Relay (4x25)";
}

function tcText(text, opts = {}) {
  const runs = [];
  if (Array.isArray(text)) {
    for (const r of text) runs.push(new TextRun(r));
  } else {
    runs.push(new TextRun({ text: String(text), bold: opts.bold }));
  }
  return new TableCell({
    width: { size: opts.width, type: WidthType.DXA },
    shading: opts.shading
      ? { fill: opts.shading, type: ShadingType.CLEAR }
      : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
      left: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
      right: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
    },
    children: [
      new Paragraph({
        alignment: opts.align || AlignmentType.LEFT,
        children: runs,
      }),
    ],
  });
}

function makeIndividualTable(ev, mode) {
  if (mode !== "vs") {
    const soloCols = [800, 4760, 1400, 2400];
    const headerRow = new TableRow({
      tableHeader: true,
      children: [
        tcText("Slot", { width: soloCols[0], shading: "1F3864", bold: true }),
        tcText("Swimmer", { width: soloCols[1], shading: "1F3864", bold: true }),
        tcText("Time", { width: soloCols[2], shading: "1F3864", bold: true, align: AlignmentType.RIGHT }),
        tcText("Notes", { width: soloCols[3], shading: "1F3864", bold: true }),
      ],
    });
    const rows = [headerRow];
    if (!ev.us || ev.us.length === 0) {
      rows.push(
        new TableRow({
          children: [
            tcText("—", { width: soloCols[0] }),
            tcText("(no eligible swimmer)", { width: soloCols[1] }),
            tcText("", { width: soloCols[2] }),
            tcText("", { width: soloCols[3] }),
          ],
        })
      );
    } else {
      for (const a of ev.us) {
        const note = a.swim_up ? `swim-up from ${a.swim_up}` : "";
        rows.push(
          new TableRow({
            children: [
              tcText(a.slot, { width: soloCols[0] }),
              tcText(a.name, { width: soloCols[1] }),
              tcText(fmtTime(a.time), { width: soloCols[2], align: AlignmentType.RIGHT }),
              tcText(note, { width: soloCols[3] }),
            ],
          })
        );
      }
    }
    return new Table({
      width: { size: 9360, type: WidthType.DXA },
      columnWidths: soloCols,
      rows,
    });
  }

  // VS mode table — three OH rows (A/B/C) side-by-side with opp times
  const vsCols = [700, 3000, 1200, 800, 1200, 1800, 660];
  const headerRow = new TableRow({
    tableHeader: true,
    children: [
      tcText("Slot", { width: vsCols[0], shading: "1F3864", bold: true }),
      tcText("OH Swimmer", { width: vsCols[1], shading: "1F3864", bold: true }),
      tcText("OH Time", { width: vsCols[2], shading: "1F3864", bold: true, align: AlignmentType.RIGHT }),
      tcText("Pts", { width: vsCols[3], shading: "1F3864", bold: true, align: AlignmentType.RIGHT }),
      tcText("Opp Time", { width: vsCols[4], shading: "1F3864", bold: true, align: AlignmentType.RIGHT }),
      tcText("Opp Swimmer", { width: vsCols[5], shading: "1F3864", bold: true }),
      tcText("Place", { width: vsCols[6], shading: "1F3864", bold: true, align: AlignmentType.CENTER }),
    ],
  });
  const rows = [headerRow];
  const slots = ["A", "B", "C"];
  for (let i = 0; i < 3; i++) {
    const a = (ev.us || [])[i] || {};
    const o = (ev.opp || [])[i] || {};
    rows.push(
      new TableRow({
        children: [
          tcText(slots[i], { width: vsCols[0] }),
          tcText(a.name || "—", { width: vsCols[1] }),
          tcText(fmtTime(a.time), { width: vsCols[2], align: AlignmentType.RIGHT }),
          tcText(a.points != null ? a.points.toFixed(1) : "", { width: vsCols[3], align: AlignmentType.RIGHT }),
          tcText(fmtTime(o.time), { width: vsCols[4], align: AlignmentType.RIGHT }),
          tcText(o.name || "—", { width: vsCols[5] }),
          tcText(a.place ? String(a.place) : "", { width: vsCols[6], align: AlignmentType.CENTER }),
        ],
      })
    );
  }
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: vsCols,
    rows,
  });
}

function makeRelayTable(rel, mode) {
  if (!rel || !rel.us_legs || rel.us_legs.length === 0) {
    return new Paragraph({
      children: [
        new TextRun({ text: "  (not fielded — insufficient eligible swimmers)", italics: true, color: "888888" }),
      ],
    });
  }
  if (mode === "vs") {
    const cols = [1200, 1200, 5200, 1760];
    const rows = [
      new TableRow({
        tableHeader: true,
        children: [
          tcText("Leg", { width: cols[0], shading: "1F3864", bold: true }),
          tcText("Time", { width: cols[1], shading: "1F3864", bold: true, align: AlignmentType.RIGHT }),
          tcText("Swimmer", { width: cols[2], shading: "1F3864", bold: true }),
          tcText("", { width: cols[3], shading: "1F3864", bold: true }),
        ],
      }),
    ];
    for (const leg of rel.us_legs) {
      rows.push(
        new TableRow({
          children: [
            tcText(leg.label, { width: cols[0] }),
            tcText(fmtTime(leg.time), { width: cols[1], align: AlignmentType.RIGHT }),
            tcText(leg.name, { width: cols[2] }),
            tcText("", { width: cols[3] }),
          ],
        })
      );
    }
    const verdict =
      rel.opp_total == null
        ? "no opp time"
        : rel.us_total + 1.0 < rel.opp_total
        ? "WIN"
        : rel.us_total > rel.opp_total + 1.0
        ? "LOSS"
        : "TIE/CLOSE";
    rows.push(
      new TableRow({
        children: [
          tcText("TOTAL", { width: cols[0], bold: true, shading: "F2F2F2" }),
          tcText(fmtTime(rel.us_total), { width: cols[1], bold: true, align: AlignmentType.RIGHT, shading: "F2F2F2" }),
          tcText(`Opp total: ${fmtTime(rel.opp_total)}`, { width: cols[2], shading: "F2F2F2" }),
          tcText(verdict, { width: cols[3], bold: true, align: AlignmentType.CENTER, shading: "F2F2F2" }),
        ],
      })
    );
    return new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: cols, rows });
  }
  const cols = [1200, 1200, 6960];
  const rows = [
    new TableRow({
      tableHeader: true,
      children: [
        tcText("Leg", { width: cols[0], shading: "1F3864", bold: true }),
        tcText("Time", { width: cols[1], shading: "1F3864", bold: true, align: AlignmentType.RIGHT }),
        tcText("Swimmer", { width: cols[2], shading: "1F3864", bold: true }),
      ],
    }),
  ];
  for (const leg of rel.us_legs) {
    rows.push(
      new TableRow({
        children: [
          tcText(leg.label, { width: cols[0] }),
          tcText(fmtTime(leg.time), { width: cols[1], align: AlignmentType.RIGHT }),
          tcText(leg.name, { width: cols[2] }),
        ],
      })
    );
  }
  rows.push(
    new TableRow({
      children: [
        tcText("TOTAL", { width: cols[0], bold: true, shading: "F2F2F2" }),
        tcText(fmtTime(rel.us_total), { width: cols[1], bold: true, align: AlignmentType.RIGHT, shading: "F2F2F2" }),
        tcText("", { width: cols[2], shading: "F2F2F2" }),
      ],
    })
  );
  return new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: cols, rows });
}

function buildAgeGroupSection(grp, mode) {
  const children = [];
  children.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 360, after: 120 },
      children: [
        new TextRun({
          text: ageGenderLabel(grp.age_group, grp.gender),
          bold: true,
          size: 28,
          color: "1F3864",
        }),
      ],
    })
  );
  for (const ev of grp.individuals) {
    children.push(
      new Paragraph({
        spacing: { before: 200, after: 80 },
        children: [
          new TextRun({
            text: `#${ev.event_number}  ${eventTitle(grp.age_group, ev.stroke)}`,
            bold: true,
            size: 24,
          }),
          mode === "vs" && ev.our_pts != null
            ? new TextRun({
                text: `   ${ev.result || ""}  ${ev.our_pts.toFixed(1)} pts`,
                bold: true,
                color: ev.result === "WIN" ? "2E7D32" : ev.result === "LOSS" ? "B71C1C" : "555555",
              })
            : new TextRun(""),
        ],
      })
    );
    children.push(makeIndividualTable(ev, mode));
  }
  if (grp.relay) {
    children.push(
      new Paragraph({
        spacing: { before: 240, after: 80 },
        children: [
          new TextRun({
            text: `#${grp.relay.event_number}  ${relayTitle(grp.age_group)}`,
            bold: true,
            size: 24,
          }),
        ],
      })
    );
    const rel = makeRelayTable(grp.relay, mode);
    if (rel instanceof Table) children.push(rel);
    else children.push(rel);
  }
  return children;
}

function buildMixedAgeSection(rel, gender, mode) {
  const children = [];
  children.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 360, after: 120 },
      children: [
        new TextRun({
          text: `Mixed-Age ${gender === "B" ? "Boys" : "Girls"} Free Relay`,
          bold: true,
          size: 28,
          color: "1F3864",
        }),
      ],
    })
  );
  children.push(
    new Paragraph({
      spacing: { before: 200, after: 80 },
      children: [
        new TextRun({
          text: `#${rel ? rel.event_number : ""}  200m Free Relay (4x50, one swimmer per age band)`,
          bold: true,
          size: 24,
        }),
      ],
    })
  );
  const t = makeRelayTable(rel, mode);
  children.push(t);
  return children;
}

function main() {
  const outPath = process.argv[2];
  if (!outPath) {
    console.error("Usage: cat lineup.json | node _lineup_doc.js out.docx");
    process.exit(2);
  }
  const data = JSON.parse(fs.readFileSync(0, "utf8"));
  const mode = data.mode;

  const titleRuns = [
    new TextRun({
      text:
        mode === "vs"
          ? `Orange Hunt vs ${data.opp_team}: Optimal Lineup`
          : "Orange Hunt: Optimal Lineup",
      bold: true,
      size: 36,
    }),
  ];

  const children = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 120 },
      children: titleRuns,
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 120 },
      children: [
        new TextRun({
          text:
            mode === "vs"
              ? `OH: ${data.us_swimmers_count} swimmers   |   ${data.opp_team}: ${data.opp_swimmers_count} swimmers   |   Generated ${data.generated}`
              : `${data.us_swimmers_count} swimmers   |   Generated ${data.generated}`,
          color: "555555",
          italics: true,
        }),
      ],
    }),
  ];

  if (mode === "vs" && data.totals) {
    const verdict = data.totals.verdict;
    const color = verdict === "WIN" ? "2E7D32" : verdict === "LOSS" ? "B71C1C" : "555555";
    children.push(
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 240 },
        children: [
          new TextRun({
            text: `Projected: OH ${data.totals.us_total_points.toFixed(1)} – ${data.totals.opp_total_points.toFixed(1)} ${data.opp_team}   [${verdict}]`,
            bold: true,
            size: 28,
            color,
          }),
        ],
      })
    );
  }

  // Boys section: 8U -> 15-18, then mixed-age boys
  children.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      spacing: { before: 240, after: 120 },
      children: [
        new TextRun({ text: "BOYS", bold: true, size: 32, color: "1F3864" }),
      ],
    })
  );
  for (const ag of AGE_ORDER) {
    const grp = data.by_age_gender.find(g => g.gender === "B" && g.age_group === ag);
    if (!grp) continue;
    for (const child of buildAgeGroupSection(grp, mode)) children.push(child);
  }
  if (data.mixed_age && data.mixed_age.B) {
    for (const child of buildMixedAgeSection(data.mixed_age.B, "B", mode)) children.push(child);
  }

  // Page break before girls
  children.push(new Paragraph({ children: [new PageBreak()] }));

  children.push(
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      spacing: { before: 240, after: 120 },
      children: [
        new TextRun({ text: "GIRLS", bold: true, size: 32, color: "C2185B" }),
      ],
    })
  );
  for (const ag of AGE_ORDER) {
    const grp = data.by_age_gender.find(g => g.gender === "G" && g.age_group === ag);
    if (!grp) continue;
    for (const child of buildAgeGroupSection(grp, mode)) children.push(child);
  }
  if (data.mixed_age && data.mixed_age.G) {
    for (const child of buildMixedAgeSection(data.mixed_age.G, "G", mode)) children.push(child);
  }

  if (mode === "vs" && data.totals) {
    children.push(new Paragraph({ children: [new PageBreak()] }));
    children.push(
      new Paragraph({
        heading: HeadingLevel.HEADING_1,
        spacing: { before: 240, after: 120 },
        children: [new TextRun({ text: "Projected Score", bold: true, size: 32 })],
      })
    );
    const verdict = data.totals.verdict;
    const color = verdict === "WIN" ? "2E7D32" : verdict === "LOSS" ? "B71C1C" : "555555";
    children.push(
      new Paragraph({
        spacing: { after: 120 },
        children: [
          new TextRun({
            text: `OH ${data.totals.us_total_points.toFixed(1)} – ${data.totals.opp_total_points.toFixed(1)} ${data.opp_team}   [${verdict}]`,
            bold: true,
            size: 32,
            color,
          }),
        ],
      })
    );
    children.push(
      new Paragraph({
        spacing: { after: 80 },
        children: [
          new TextRun({
            text: `Scoring: 5-3-1 for individual events, 5-0 for relays. 211 points clinches out of 420.`,
            italics: true,
            color: "555555",
          }),
        ],
      })
    );
    children.push(
      new Paragraph({
        children: [
          new TextRun({
            text: `Conservative variance: individual races within 0.3s and relays within 1.0s are credited to the opponent for projection.`,
            italics: true,
            color: "555555",
          }),
        ],
      })
    );
  }

  const doc = new Document({
    styles: {
      default: { document: { run: { font: "Arial", size: 22 } } },
      paragraphStyles: [
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 32, bold: true, font: "Arial" },
          paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 0 },
        },
        {
          id: "Heading2",
          name: "Heading 2",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 28, bold: true, font: "Arial" },
          paragraph: { spacing: { before: 180, after: 120 }, outlineLevel: 1 },
        },
      ],
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: PAGE_W, height: PAGE_H },
            margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
          },
        },
        children,
      },
    ],
  });

  Packer.toBuffer(doc).then(buf => {
    fs.writeFileSync(outPath, buf);
    console.log(`wrote ${outPath}`);
  });
}

main();
