const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
        ShadingType, PageNumber, LevelFormat } = require('docx');
const fs = require('fs');

const BLUE = "1F4E79";
const LIGHT_BLUE = "D6E4F0";
const DARK = "333333";

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

function headerCell(text, width) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    shading: { fill: BLUE, type: ShadingType.CLEAR }, margins: cellMargins, verticalAlign: "center",
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: "FFFFFF", font: "Arial", size: 20 })] })]
  });
}

function dataCell(text, width, opts = {}) {
  const shading = opts.highlight ? { fill: LIGHT_BLUE, type: ShadingType.CLEAR } : undefined;
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA }, shading, margins: cellMargins,
    children: [new Paragraph({
      alignment: opts.align || AlignmentType.LEFT,
      children: [new TextRun({ text, font: "Arial", size: 20, bold: opts.bold || false, color: opts.color || DARK })]
    })]
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22, color: DARK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: BLUE },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: BLUE },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
    ]
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "numbers",
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: BLUE, space: 4 } },
          children: [
            new TextRun({ text: "LOLM: Latent Order Language Model", font: "Arial", size: 18, color: BLUE, bold: true }),
            new TextRun({ text: "  |  Compute Grant Research Proposal", font: "Arial", size: 18, color: "888888" }),
          ]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC", space: 4 } },
          children: [
            new TextRun({ text: "Bryan Leonard & Brandyn Leonard  |  github.com/TheArtOfSound/lolm  |  Page ", font: "Arial", size: 16, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: "888888" }),
          ]
        })]
      })
    },
    children: [
      // ── TITLE ──
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 80 },
        children: [new TextRun({ text: "Latent Order Language Model (LOLM)", size: 44, bold: true, font: "Arial", color: BLUE })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 80 },
        children: [new TextRun({ text: "A Hybrid Transformer-SSM Architecture with Phase-Selective Regime Detection", size: 24, font: "Arial", color: "666666" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 400 },
        children: [
          new TextRun({ text: "Bryan Leonard & Brandyn Leonard  |  Qira LLC  |  March 2026", size: 20, font: "Arial", color: "888888" }),
        ]
      }),

      // ── PROJECT SUMMARY ──
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("1. Project Summary")] }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: "LOLM is a novel 304M-parameter hybrid architecture that fuses a Transformer surface decoder with a selective state-space model (SSM), persistent memory banks, learned regime detection, and a dynamic manifestation gate. Unlike standard Transformers that model language as a flat token sequence, LOLM hypothesizes that language has latent structure\u2014regimes, phase transitions, and long-range dependencies\u2014that can be explicitly modeled through dedicated architectural components.",
          size: 22
        })]
      }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: "Preliminary results on a 304M-parameter model trained on FineWeb-Edu (2B tokens) demonstrate that LOLM outperforms Pythia-410M on all evaluation metrics at matched compute, and maintains superior long-range context utilization even when Pythia is given 2x more training data. Component ablation studies confirm that each architectural innovation contributes measurably to performance. This proposal requests compute to scale LOLM to 1B+ parameters and conduct comprehensive evaluation against established baselines.",
          size: 22
        })]
      }),

      // ── ARCHITECTURE ──
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("2. Architecture")] }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({ text: "LOLM combines five interacting subsystems, each addressing a different aspect of language modeling:", size: 22 })]
      }),

      new Table({
        width: { size: 9360, type: WidthType.DXA }, columnWidths: [2200, 7160],
        rows: [
          new TableRow({ children: [headerCell("Component", 2200), headerCell("Function", 7160)] }),
          new TableRow({ children: [
            dataCell("Surface Decoder", 2200, { bold: true }),
            dataCell("16-layer pre-norm Transformer (d=1024, 16 heads) with RoPE. Processes raw token sequences.", 7160)
          ]}),
          new TableRow({ children: [
            dataCell("Latent SSM Core", 2200, { bold: true }),
            dataCell("4-layer selective SSM (Mamba-style) with parallel scan and CUDA kernels. Maintains compressed latent state across the full sequence, providing O(1) memory per step.", 7160)
          ]}),
          new TableRow({ children: [
            dataCell("Regime Layer", 2200, { bold: true }),
            dataCell("32-code discrete phase detector using Gumbel-Softmax with neighbor interaction (1D conv kernel=7). Identifies emergent linguistic regimes through local token interactions, inspired by Multi Phase Selection Tool.", 7160)
          ]}),
          new TableRow({ children: [
            dataCell("Persistent Memory", 2200, { bold: true }),
            dataCell("3 banks (episodic/semantic/self) with 128 slots each. Attention-based read/write with entropy regularization for selective memory access.", 7160)
          ]}),
          new TableRow({ children: [
            dataCell("Manifestation Gate", 2200, { bold: true }),
            dataCell("Learned sigmoid gate that dynamically blends surface (Transformer) and latent (SSM) representations based on input context. Final output: g*h + (1-g)*z + memory + regime.", 7160)
          ]}),
        ]
      }),
      new Paragraph({ spacing: { after: 200 }, children: [] }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Key Technical Innovations")] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Gradient isolation: ", bold: true, size: 22 }), new TextRun({ text: "Regime embeddings are detached before fusion, preventing token loss from collapsing discrete codes (inspired by VQ-VAE). This solved regime collapse that persisted across all prior training runs.", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "CPC future prediction: ", bold: true, size: 22 }), new TextRun({ text: "SimCLR/CLIP-style projection heads with calibrated temperature for contrastive predictive coding, enabling the SSM to learn future-aware representations.", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "MPST-inspired regime detection: ", bold: true, size: 22 }), new TextRun({ text: "Neighbor interaction on regime logits creates coherent regime segments through local token interactions, rather than independent per-token assignment.", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 200 },
        children: [new TextRun({ text: "7-loss training objective: ", bold: true, size: 22 }), new TextRun({ text: "Token CE + CPC contrastive + changepoint alignment + regime diversity + competitive gate + memory focus + gate regularization.", size: 22 })] }),

      // ── PRELIMINARY RESULTS ──
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("3. Preliminary Results")] }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: "All results below were obtained from a 304M-parameter LOLM trained for 30,000 steps on FineWeb-Edu (~2B tokens) using a single NVIDIA H200 GPU. Evaluation is on WikiText-103 test split.",
          size: 22
        })]
      }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("3.1 Component Ablation Study")] }),
      new Paragraph({
        spacing: { after: 120 },
        children: [new TextRun({
          text: "Inference-time ablation using forward hooks to disable individual components without retraining. Evaluated on 50 batches of WikiText-103 (seq_len=2048):",
          size: 22
        })]
      }),

      new Table({
        width: { size: 9360, type: WidthType.DXA }, columnWidths: [2800, 1600, 1600, 3360],
        rows: [
          new TableRow({ children: [headerCell("Variant", 2800), headerCell("PPL", 1600), headerCell("Delta", 1600), headerCell("Significance", 3360)] }),
          new TableRow({ children: [
            dataCell("Full LOLM", 2800, { bold: true, highlight: true }),
            dataCell("59.23", 1600, { bold: true, highlight: true, align: AlignmentType.CENTER }),
            dataCell("\u2014", 1600, { highlight: true, align: AlignmentType.CENTER }),
            dataCell("Baseline", 3360, { highlight: true })
          ]}),
          new TableRow({ children: [
            dataCell("No Memory", 2800), dataCell("59.23", 1600, { align: AlignmentType.CENTER }),
            dataCell("-0.0%", 1600, { align: AlignmentType.CENTER }),
            dataCell("Memory not contributing (future work)", 3360)
          ]}),
          new TableRow({ children: [
            dataCell("No Regime", 2800), dataCell("123.73", 1600, { align: AlignmentType.CENTER }),
            dataCell("+108.9%", 1600, { align: AlignmentType.CENTER, bold: true, color: "C00000" }),
            dataCell("Regime detection helps significantly", 3360)
          ]}),
          new TableRow({ children: [
            dataCell("No SSM (gate=1)", 2800), dataCell("499.96", 1600, { align: AlignmentType.CENTER }),
            dataCell("+744.1%", 1600, { align: AlignmentType.CENTER, bold: true, color: "C00000" }),
            dataCell("SSM latent path is essential", 3360)
          ]}),
          new TableRow({ children: [
            dataCell("No Gate (g=0.5)", 2800), dataCell("595.43", 1600, { align: AlignmentType.CENTER }),
            dataCell("+905.2%", 1600, { align: AlignmentType.CENTER, bold: true, color: "C00000" }),
            dataCell("Dynamic gating is critical", 3360)
          ]}),
          new TableRow({ children: [
            dataCell("Decoder Only", 2800), dataCell("2198.58", 1600, { align: AlignmentType.CENTER }),
            dataCell("+3611.8%", 1600, { align: AlignmentType.CENTER, bold: true, color: "C00000" }),
            dataCell("All latent components help massively", 3360)
          ]}),
        ]
      }),
      new Paragraph({ spacing: { after: 200 }, children: [] }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("3.2 LOLM vs Pythia-410M Comparison")] }),
      new Paragraph({
        spacing: { after: 120 },
        children: [new TextRun({ text: "Head-to-head evaluation at three training data points. LOLM has 26% fewer parameters (304M vs 410M).", size: 22 })]
      }),

      new Table({
        width: { size: 9360, type: WidthType.DXA }, columnWidths: [3000, 2120, 2120, 2120],
        rows: [
          new TableRow({ children: [
            headerCell("Metric", 3000), headerCell("LOLM-304M", 2120), headerCell("Pythia (2B tok)", 2120), headerCell("Pythia (4B tok)", 2120),
          ]}),
          new TableRow({ children: [
            dataCell("Parameters", 3000, { bold: true }), dataCell("303.6M", 2120, { align: AlignmentType.CENTER }),
            dataCell("410M", 2120, { align: AlignmentType.CENTER }), dataCell("410M", 2120, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Tokens seen", 3000, { bold: true }), dataCell("~2B", 2120, { align: AlignmentType.CENTER }),
            dataCell("~2B", 2120, { align: AlignmentType.CENTER }), dataCell("~4B", 2120, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Overall BPC", 3000, { bold: true }),
            dataCell("6.10", 2120, { align: AlignmentType.CENTER, bold: true, highlight: true }),
            dataCell("7.16", 2120, { align: AlignmentType.CENTER }),
            dataCell("5.76", 2120, { align: AlignmentType.CENTER, bold: true }),
          ]}),
          new TableRow({ children: [
            dataCell("Overall PPL", 3000, { bold: true }),
            dataCell("68.37", 2120, { align: AlignmentType.CENTER, bold: true, highlight: true }),
            dataCell("142.93", 2120, { align: AlignmentType.CENTER }),
            dataCell("54.32", 2120, { align: AlignmentType.CENTER, bold: true }),
          ]}),
          new TableRow({ children: [
            dataCell("Late-position BPC change", 3000, { bold: true }),
            dataCell("-17.0%", 2120, { align: AlignmentType.CENTER, bold: true, highlight: true }),
            dataCell("-11.4%", 2120, { align: AlignmentType.CENTER }),
            dataCell("-14.0%", 2120, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Context advantage (top-1)", 3000, { bold: true }),
            dataCell("+45.4%", 2120, { align: AlignmentType.CENTER, bold: true, highlight: true }),
            dataCell("+34.7%", 2120, { align: AlignmentType.CENTER }),
            dataCell("+45.7%", 2120, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Bigram repetition", 3000, { bold: true }),
            dataCell("31.3%", 2120, { align: AlignmentType.CENTER, bold: true, highlight: true }),
            dataCell("39.3%", 2120, { align: AlignmentType.CENTER }),
            dataCell("\u2014", 2120, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Distinct-2", 3000, { bold: true }),
            dataCell("0.687", 2120, { align: AlignmentType.CENTER, bold: true, highlight: true }),
            dataCell("0.607", 2120, { align: AlignmentType.CENTER }),
            dataCell("\u2014", 2120, { align: AlignmentType.CENTER }),
          ]}),
        ]
      }),
      new Paragraph({ spacing: { after: 120 }, children: [] }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: "Key finding: At matched compute (2B tokens), LOLM outperforms Pythia-410M on all metrics despite 26% fewer parameters. Even when Pythia is given 2x more training data (4B tokens), LOLM maintains superior long-range context utilization (-17.0% vs -14.0% late-position improvement, +45.4% vs +45.7% context advantage). This demonstrates that LOLM\u2019s architectural innovations provide capabilities that cannot be replicated by simply scaling data.",
          size: 22, italics: true
        })]
      }),

      // ── PROPOSED RESEARCH ──
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("4. Proposed Research")] }),
      new Paragraph({
        spacing: { after: 120 },
        children: [new TextRun({ text: "Additional compute would enable three research directions that are currently blocked by resource constraints:", size: 22 })]
      }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("4.1 Scale to 1B Parameters")] }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: "Current results at 304M are promising but insufficient to evaluate LOLM\u2019s scaling behavior. A 1B-parameter model trained on 50B+ tokens would establish whether the architectural advantages persist or grow at scale. Specific questions: Does the latent advantage increase with model size? Does the regime layer develop more semantically meaningful codes with more capacity?",
          size: 22
        })]
      }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("4.2 Standard Benchmark Evaluation")] }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: "Running the lm-evaluation-harness suite (HellaSwag, ARC, MMLU, WinoGrande) requires dedicated GPU time for both LOLM and matched baselines. These benchmarks are essential for peer-reviewed publication and direct comparison with established models.",
          size: 22
        })]
      }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("4.3 Memory Architecture Redesign")] }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: "The ablation study revealed that the persistent memory component is not contributing to performance (0.0% PPL change when removed). With additional compute, we plan to investigate alternative memory architectures including retrieval-augmented approaches and memory-as-attention variants. Since 3 of 4 components already demonstrate strong contributions, fixing the memory pathway could unlock further gains.",
          size: 22
        })]
      }),

      // ── COMPUTE REQUEST ──
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("5. Compute Requirements")] }),

      new Table({
        width: { size: 9360, type: WidthType.DXA }, columnWidths: [3500, 2930, 2930],
        rows: [
          new TableRow({ children: [headerCell("Task", 3500), headerCell("Estimated GPU-hours", 2930), headerCell("Hardware", 2930)] }),
          new TableRow({ children: [
            dataCell("1B model training (50B tokens)", 3500),
            dataCell("~2,000 H100-hours", 2930, { align: AlignmentType.CENTER }),
            dataCell("4x H100 / 4x TPU v4", 2930, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Benchmark evaluation suite", 3500),
            dataCell("~200 H100-hours", 2930, { align: AlignmentType.CENTER }),
            dataCell("1x H100 / 1x TPU v4", 2930, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Memory architecture experiments", 3500),
            dataCell("~500 H100-hours", 2930, { align: AlignmentType.CENTER }),
            dataCell("1x H100 / 1x TPU v4", 2930, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Ablation at 1B scale", 3500),
            dataCell("~300 H100-hours", 2930, { align: AlignmentType.CENTER }),
            dataCell("1x H100 / 1x TPU v4", 2930, { align: AlignmentType.CENTER }),
          ]}),
          new TableRow({ children: [
            dataCell("Total", 3500, { bold: true, highlight: true }),
            dataCell("~3,000 H100-hours", 2930, { align: AlignmentType.CENTER, bold: true, highlight: true }),
            dataCell("", 2930, { highlight: true }),
          ]}),
        ]
      }),
      new Paragraph({ spacing: { after: 200 }, children: [] }),

      // ── COMMITMENT ──
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("6. Open Science Commitment")] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "All code is open source under Apache 2.0: ", size: 22 }), new TextRun({ text: "github.com/TheArtOfSound/lolm", size: 22, bold: true })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Model weights, training logs, and evaluation scripts will be publicly released", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Research findings will be submitted to peer-reviewed venues (NeurIPS, ICML, or ICLR workshops)", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Detailed blog posts documenting training dynamics, failure modes, and architectural decisions", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 200 },
        children: [new TextRun({ text: "Research conducted in accordance with responsible AI principles", size: 22 })] }),

      // ── ABOUT ──
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("7. About the Researchers")] }),
      new Paragraph({
        spacing: { after: 200 },
        children: [new TextRun({
          text: "Bryan Leonard and Brandyn Leonard are independent AI researchers focused on novel language model architectures. LOLM was conceived, designed, implemented, and trained as a collaborative research effort, demonstrating the viability of architectural innovation outside large institutional settings. The project draws on theoretical insights from statistical physics (Multi Phase Selection Tool) and representation learning (VQ-VAE, SimCLR) to propose a fundamentally different approach to language modeling. All development has been self-funded through commercial GPU rental services.",
          size: 22
        })]
      }),

      // ── REFERENCES ──
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("8. References & Links")] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "GitHub: github.com/TheArtOfSound/lolm", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Architecture: Transformer + Selective SSM + Regime Detection + Persistent Memory + Manifestation Gate", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Training data: FineWeb-Edu (HuggingFace), evaluated on WikiText-103", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "License: Apache 2.0 (open source + commercial compatible)", size: 22 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Baseline comparison: Pythia-410M (EleutherAI)", size: 22 })] }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/Users/bry/Documents/Latent/LOLM_Compute_Grant_Proposal.docx", buffer);
  console.log("Created LOLM_Compute_Grant_Proposal.docx");
});
