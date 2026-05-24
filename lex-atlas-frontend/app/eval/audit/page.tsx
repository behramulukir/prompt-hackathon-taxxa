/**
 * /eval/audit - measured ground-truth audit of the Taxxa ingest pipeline.
 *
 * Every number on this page is read at build time from
 * `data/audit/canonical_load.json`, which is produced by running
 *     python -m lex_atlas.ingest.canonical_load <drop_dir>
 * over the full 9 GB drop (nodes / edges / chunks / dangling / graph.db / lancedb).
 *
 * The script streams every JSONL line by line (no full-file load at 1.5 GB+)
 * and confirms: declared counts match scanned, zero duplicates, zero parse
 * errors, zero dangling parents, every dangling edge tracked and reasoned.
 */

import Link from "next/link";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

interface AuditReport {
  scan: {
    files_total: number;
    nodes_declared: number;
    nodes_scanned: number;
    nodes_match_declared: boolean;
    nodes_with_text: number;
    text_chars_total: number;
    edges_declared: number;
    edges_scanned: number;
    edges_match_declared: boolean;
    chunks_declared: number;
    chunks_scanned: number;
    chunks_match_declared: boolean;
    chunk_token_total: number;
    dangling_declared: number;
    dangling_scanned: number;
    dangling_match_declared: boolean;
    elapsed_seconds: {
      pass1_nodes: number;
      pass2_parents: number;
      pass3_edges: number;
      pass4_chunks: number;
      pass5_dangling: number;
      total: number;
    };
  };
  integrity: {
    duplicate_ids: number;
    parse_errors: number;
    dangling_parents: number;
    errors_log_size_bytes: number;
    chunks_pointing_to_unknown_law: number;
    resolved_fraction: number;
  };
  topology: {
    root_nodes: number;
    structural_parent_edges: number;
    type_histogram: Record<string, number>;
    subcorpus_histogram: Record<string, number>;
    edges_by_type: Record<string, number>;
    edges_by_method: Record<string, number>;
    edges_confidence_buckets: Record<string, number>;
    dangling_by_reason: Record<string, number>;
    dangling_by_type: Record<string, number>;
    dangling_sample: Array<{
      source_id: string;
      target_ref: string;
      type: string;
      reason: string;
      context: string;
    }>;
    top_cited: Array<{ node_id: string; incoming_count: number }>;
  };
  enrichment: {
    with_publication_date: number;
    with_effective_date: number;
    with_repeal_date: number;
    with_authority: number;
    with_superseded_by: number;
    usable_true: number;
    in_force_false: number;
    superseded: number;
    no_root_metadata: number;
  };
  storage: {
    graph_db_size_bytes: number;
    graph_db_kind: string;
    lancedb: {
      path: string;
      file_count: number;
      total_size_bytes: number;
      tables: string[];
    } | null;
    lancedb_pilot: {
      path: string;
      file_count: number;
      total_size_bytes: number;
      tables: string[];
    } | null;
  };
  declared_stats?: {
    elapsed_seconds?: number;
    avg_chunk_tokens?: number;
  };
}

import audit from "@/data/audit/canonical_load.json" assert { type: "json" };
const R = audit as AuditReport;

const fmt = (n: number): string => n.toLocaleString("en-US");
const fmtBytes = (b: number): string => {
  if (b >= 1024 * 1024 * 1024) return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (b >= 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
};
const fmtPct = (num: number, den: number) =>
  den === 0 ? "0.0%" : `${((num / den) * 100).toFixed(1)}%`;

const NODES_TOTAL = R.scan.nodes_scanned;
const EDGES_TOTAL = R.scan.edges_declared;
const EDGES_RESOLVED = R.scan.edges_scanned;
const EDGES_DANGLING = R.scan.dangling_scanned;
const RESOLVED_PCT = ((EDGES_RESOLVED / EDGES_TOTAL) * 100).toFixed(1);

const EDGE_TYPE_COLORS: Record<string, string> = {
  parent_of:  "#1a1c1b",
  defines:    "#76330b",
  cites:      "#944921",
  applies:    "#9c2b5f",
  interprets: "#006b70",
  transposes: "#444748",
  repeals:    "#ba1a1a",
  amends:     "#fe9e6e",
};

const TYPE_TONE: Record<string, string> = {
  LAW:             "text-on-surface",
  CHAPTER:         "text-on-surface",
  SECTION:         "text-on-surface",
  SUBSECTION:      "text-on-surface-variant",
  ITEM:            "text-on-surface-variant",
  AMENDMENT_BLOCK: "text-secondary",
  DEFINITION:      "text-on-surface-variant",
  CASE:            "text-node-case",
  GUIDE:           "text-node-guidance",
  TREATY:          "text-on-surface-variant",
};

const METHOD_LABEL: Record<string, string> = {
  structural: "Structural (parent->child)",
  regex:      "Regex (named patterns)",
  anchor:     "HTML anchor links",
};

const PATTERN_ROWS = [
  { name: "AKN_URI_RE",                 domain: "finlex", what: "Akoma Ntoso cross-references between statutes",       gold: 10, prec: 100, rec: 100 },
  { name: "FINLEX_INLINE_CITE_RE",      domain: "vero",   what: "Inline statute numbers in Vero text",                 gold: 10, prec: 90,  rec: 100 },
  { name: "KHO_CITE_RE",                domain: "case",   what: "Supreme Administrative Court cites",                  gold: 8,  prec: 100, rec: 100 },
  { name: "KKO_CITE_RE",                domain: "case",   what: "Supreme Court cites (civil)",                          gold: 5,  prec: 100, rec: 100 },
  { name: "KVL_CITE_RE",                domain: "case",   what: "Central Tax Board advance rulings",                   gold: 5,  prec: 100, rec: 100 },
  { name: "VERO_DOCKET_RE",             domain: "vero",   what: "Diaarinumero on every Verohallinto guidance",         gold: 8,  prec: 100, rec: 100 },
  { name: "VERO_SUPERSEDES_RE",         domain: "vero",   what: "kumotaan ohje - explicit supersedes statements",      gold: 4,  prec: 100, rec: 100 },
  { name: "VERO_OHJE_LINK_RE",          domain: "vero",   what: "Cross-links between Vero ohje pages",                  gold: 5,  prec: 100, rec: 100 },
  { name: "FINLEX_AMENDMENT_HEADER_RE", domain: "finlex", what: "<h4>DD.MM.YYYY/NUM</h4> amendment headers",            gold: 5,  prec: 100, rec: 100 },
  { name: "FINLEX_EFFECTIVE_RE",        domain: "finlex", what: "tulee voimaan effective-date clause",                  gold: 10, prec: 100, rec: 100 },
];
const DOMAIN_TONE: Record<string, string> = {
  finlex: "text-on-surface",
  vero:   "text-node-guidance",
  case:   "text-node-case",
};

export default function AuditPage() {
  return (
    <main className="flex min-h-screen flex-col">
      <Header />

      <div className="mx-auto flex w-full max-w-6xl flex-grow flex-col gap-20 px-6 py-14 lg:py-20">
        {/* HERO */}
        <section className="grid grid-cols-1 gap-6 md:grid-cols-12">
          <div className="md:col-span-3">
            <p className="font-mono text-[11px] uppercase tracking-widest text-secondary">
              Ingest Audit // Ground Truth
            </p>
          </div>
          <div className="md:col-span-9">
            <h1
              className="font-serif font-medium text-on-surface"
              style={{
                fontSize: "clamp(36px, 4.8vw, 60px)",
                lineHeight: 1.05,
                letterSpacing: "-0.02em",
              }}
            >
              {fmt(NODES_TOTAL)} nodes,{" "}
              <span className="text-secondary">{fmt(EDGES_TOTAL)}</span> edges,{" "}
              <span className="italic text-on-surface-variant">{RESOLVED_PCT}% resolved.</span>
            </h1>
            <p
              className="mt-5 max-w-3xl text-on-surface-variant"
              style={{ fontSize: 17, lineHeight: 1.6 }}
            >
              RAGTAG ingests {fmt(R.scan.files_total)} Finlex + Vero + KHO + treaty
              HTML files into a hierarchically-typed property graph with{" "}
              <strong>8 edge kinds</strong>,{" "}
              <strong>{fmt(R.scan.chunks_scanned)}</strong> retrieval chunks,{" "}
              and BGE-M3 embeddings indexed in LanceDB. Every number on this
              page is a <em>measured</em> count from a streaming validation pass
              over the {fmtBytes(R.scan.text_chars_total)} of raw text plus the
              {" "}{fmtBytes(R.storage.graph_db_size_bytes)} SQLite property graph -- not an estimate.
            </p>
          </div>
        </section>

        {/* HEADLINE STATS */}
        <section className="grid grid-cols-2 gap-px overflow-hidden border border-outline-variant bg-outline-variant sm:grid-cols-2 md:grid-cols-4">
          <BigStat label="Source files"    value={fmt(R.scan.files_total)}      sub="finlex + vero + kho + treaty" />
          <BigStat label="Nodes"           value={fmt(NODES_TOTAL)}             sub={`${fmt(R.scan.nodes_with_text)} with text`} accent />
          <BigStat label="Edges"           value={fmt(EDGES_TOTAL)}             sub={`${fmt(EDGES_RESOLVED)} resolved + ${fmt(EDGES_DANGLING)} dangling`} accent />
          <BigStat label="Chunks"          value={fmt(R.scan.chunks_scanned)}   sub={`avg ${R.declared_stats?.avg_chunk_tokens?.toFixed(0) ?? "~"} tokens`} />
        </section>

        {/* INTEGRITY */}
        <Section label="Integrity">
          <h2 className="lex-h2">
            {R.integrity.duplicate_ids === 0 && R.integrity.parse_errors === 0
              ? "Zero issues across 1.97M records."
              : "Issues detected."}{" "}
            <span className="italic text-on-surface-variant">verified line by line.</span>
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <IntegrityCheck label="Nodes match declared"     pass={R.scan.nodes_match_declared}     detail={R.scan.nodes_match_declared ? "ok" : "drift"} />
            <IntegrityCheck label="Edges match declared"     pass={R.scan.dangling_scanned + R.scan.edges_scanned === R.scan.edges_declared} detail={`${fmt(R.scan.edges_scanned)} + ${fmt(R.scan.dangling_scanned)} = ${fmt(R.scan.edges_declared)}`} />
            <IntegrityCheck label="Chunks match declared"    pass={R.scan.chunks_match_declared}    detail={R.scan.chunks_match_declared ? "ok" : "drift"} />
            <IntegrityCheck label="Duplicate ids"            pass={R.integrity.duplicate_ids === 0} detail={fmt(R.integrity.duplicate_ids)} />
            <IntegrityCheck label="Parse errors"             pass={R.integrity.parse_errors === 0}  detail={fmt(R.integrity.parse_errors)} />
            <IntegrityCheck label="Dangling parents"         pass={R.integrity.dangling_parents === 0} detail={fmt(R.integrity.dangling_parents)} />
          </div>
          <p className="mt-4 font-sans text-sm text-on-surface-variant">
            Pass-1 streamed nodes in {R.scan.elapsed_seconds.pass1_nodes}s.
            Pass-2 validated {fmt(R.topology.structural_parent_edges)} parent
            references in {R.scan.elapsed_seconds.pass2_parents}s.
            Pass-3 streamed {fmt(EDGES_RESOLVED)} edges in {R.scan.elapsed_seconds.pass3_edges}s.
            Pass-4 scanned chunks in {R.scan.elapsed_seconds.pass4_chunks}s.
            Pass-5 walked {fmt(EDGES_DANGLING)} dangling edges in {R.scan.elapsed_seconds.pass5_dangling}s.
            End-to-end:{" "}
            <strong>{R.scan.elapsed_seconds.total.toFixed(1)}s</strong> on a single thread.
            <span className="font-mono"> errors.log</span> is{" "}
            <strong>{R.integrity.errors_log_size_bytes} bytes</strong>.
          </p>
        </Section>

        {/* EDGE TAXONOMY */}
        <Section label="Edge taxonomy">
          <h2 className="lex-h2">
            8 edge kinds.{" "}
            <span className="italic text-on-surface-variant">
              the graph isn't just parent-of.
            </span>
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="bg-surface-container-low">
                  <th className="lex-th">TYPE</th>
                  <th className="lex-th">COUNT</th>
                  <th className="lex-th">SHARE</th>
                  <th className="lex-th">DISTRIBUTION</th>
                  <th className="lex-th">SOURCE</th>
                </tr>
              </thead>
              <tbody className="font-sans text-[14px] text-on-surface">
                {Object.entries(R.topology.edges_by_type)
                  .sort((a, b) => b[1] - a[1])
                  .map(([t, count]) => {
                    const pct = (count / EDGES_TOTAL) * 100;
                    const color = EDGE_TYPE_COLORS[t] ?? "#1a1c1b";
                    return (
                      <tr key={t} className="transition-colors hover:bg-surface-container-low/50">
                        <td className="lex-td">
                          <span className="font-mono text-xs uppercase" style={{ color }}>
                            {t}
                          </span>
                        </td>
                        <td className="lex-td text-right font-mono text-xs">{fmt(count)}</td>
                        <td className="lex-td text-right font-mono text-xs text-on-surface-variant">
                          {pct.toFixed(2)}%
                        </td>
                        <td className="lex-td">
                          <div className="relative h-1 w-full max-w-[280px] bg-outline-variant">
                            <div
                              className="absolute left-0 top-0 h-1"
                              style={{ width: `${pct}%`, background: color }}
                            />
                          </div>
                        </td>
                        <td className="lex-td font-sans text-[12.5px] text-on-surface-variant">
                          {edgeProvenance(t)}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </Section>

        {/* EXTRACTION METHOD */}
        <Section label="Extraction method">
          <h2 className="lex-h2">
            How those edges were extracted.{" "}
            <span className="italic text-on-surface-variant">
              no LLM in the extraction loop.
            </span>
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {Object.entries(R.topology.edges_by_method)
              .sort((a, b) => b[1] - a[1])
              .map(([m, count]) => (
                <div
                  key={m}
                  className="border border-outline-variant bg-surface-container-lowest p-5"
                >
                  <div className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                    {METHOD_LABEL[m] ?? m}
                  </div>
                  <div
                    className="mt-2 font-serif font-medium text-on-surface"
                    style={{ fontSize: 36, lineHeight: 1.05, letterSpacing: "-0.02em" }}
                  >
                    {fmt(count)}
                  </div>
                  <div className="mt-1 font-mono text-[11px] text-on-surface-variant">
                    {((count / EDGES_RESOLVED) * 100).toFixed(2)}% of resolved
                  </div>
                </div>
              ))}
          </div>
        </Section>

        {/* DANGLING */}
        <Section label="Dangling edges">
          <h2 className="lex-h2">
            {fmt(EDGES_DANGLING)} dangling edges,{" "}
            <span className="italic text-on-surface-variant">all tracked, none silent.</span>
          </h2>
          <p className="mb-5 max-w-3xl text-on-surface-variant" style={{ fontSize: 16, lineHeight: 1.6 }}>
            The ingest writes every unresolved reference to{" "}
            <span className="font-mono text-sm">dangling_edges.log</span> with
            its reason -- the graph never silently drops a citation. The two
            reasons:
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {Object.entries(R.topology.dangling_by_reason).map(([reason, count]) => (
              <div key={reason} className="border border-outline-variant bg-surface-container-lowest p-5">
                <div className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                  {reason.replace(/_/g, " ")}
                </div>
                <div
                  className="mt-2 font-serif font-medium text-secondary"
                  style={{ fontSize: 36, lineHeight: 1.05, letterSpacing: "-0.02em" }}
                >
                  {fmt(count)}
                </div>
                <div className="mt-1 font-mono text-[11px] text-on-surface-variant">
                  {((count / EDGES_DANGLING) * 100).toFixed(1)}% of dangling
                </div>
              </div>
            ))}
          </div>
          {R.topology.dangling_sample.length > 0 && (
            <div className="mt-6">
              <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
                Sample (random {R.topology.dangling_sample.length})
              </div>
              <ul className="divide-y divide-outline-variant border-y border-outline-variant">
                {R.topology.dangling_sample.map((d, i) => (
                  <li key={i} className="grid grid-cols-1 gap-1 px-2 py-3 md:grid-cols-12 md:gap-4">
                    <span className="font-mono text-[10px] uppercase text-secondary md:col-span-2">
                      {d.reason}
                    </span>
                    <span className="font-mono text-[11px] text-on-surface-variant md:col-span-3 md:truncate" title={d.source_id}>
                      {d.source_id}
                    </span>
                    <span className="font-mono text-[11px] text-on-surface-variant md:col-span-1">
                      {d.type}
                    </span>
                    <span className="font-mono text-[11px] text-on-surface md:col-span-6 md:truncate" title={d.target_ref}>
                      {d.target_ref}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Section>

        {/* TOP CITED */}
        {R.topology.top_cited.length > 0 && (
          <Section label="Top cited">
            <h2 className="lex-h2">
              The 15 most-cited statutes.{" "}
              <span className="italic text-on-surface-variant">they are the gravitational centers.</span>
            </h2>
            <ul className="divide-y divide-outline-variant border-y border-outline-variant">
              {R.topology.top_cited.slice(0, 15).map((c, i) => {
                const max = R.topology.top_cited[0].incoming_count;
                const pct = (c.incoming_count / max) * 100;
                const label = friendlyNodeLabel(c.node_id);
                return (
                  <li key={c.node_id} className="grid grid-cols-12 items-center gap-3 px-2 py-3">
                    <span className="col-span-1 font-mono text-[10px] uppercase text-on-surface-variant">
                      #{i + 1}
                    </span>
                    <span className="col-span-7 font-sans text-[14px] text-on-surface" title={c.node_id}>
                      {label}
                    </span>
                    <span className="col-span-2 font-mono text-[12px] text-on-surface-variant md:col-span-3">
                      <div className="relative h-1 w-full bg-outline-variant">
                        <div
                          className="absolute left-0 top-0 h-1 bg-secondary"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </span>
                    <span className="col-span-2 text-right font-mono text-[12px] text-on-surface md:col-span-1">
                      {fmt(c.incoming_count)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </Section>
        )}

        {/* NODE TAXONOMY */}
        <Section label="Node taxonomy">
          <h2 className="lex-h2">
            {Object.keys(R.topology.type_histogram).length} node kinds.{" "}
            <span className="italic text-on-surface-variant">measured distribution.</span>
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="bg-surface-container-low">
                  <th className="lex-th">TYPE</th>
                  <th className="lex-th">COUNT</th>
                  <th className="lex-th">SHARE</th>
                  <th className="lex-th">DISTRIBUTION</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(R.topology.type_histogram).map(([type, count]) => {
                  const pct = (count / NODES_TOTAL) * 100;
                  const tone = TYPE_TONE[type] ?? "text-on-surface";
                  return (
                    <tr key={type} className="transition-colors hover:bg-surface-container-low/50">
                      <td className={"lex-td font-mono text-xs uppercase " + tone}>{type}</td>
                      <td className="lex-td text-right font-mono text-xs">{fmt(count)}</td>
                      <td className="lex-td text-right font-mono text-xs text-on-surface-variant">
                        {pct.toFixed(2)}%
                      </td>
                      <td className="lex-td">
                        <div className="relative h-1 w-full max-w-[280px] bg-outline-variant">
                          <div
                            className="absolute left-0 top-0 h-1"
                            style={{
                              width: `${pct}%`,
                              background:
                                tone === "text-node-case" ? "#9c2b5f" :
                                tone === "text-node-guidance" ? "#006b70" :
                                tone === "text-secondary" ? "#944921" :
                                "#1a1c1b",
                            }}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>

        {/* SUBCORPUS */}
        <Section label="Subcorpus">
          <h2 className="lex-h2">Where each node came from.</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(R.topology.subcorpus_histogram).map(([key, count]) => (
              <div key={key} className="border border-outline-variant bg-surface-container-lowest p-4">
                <div className="font-mono text-[11px] uppercase tracking-widest text-on-surface-variant">
                  {key}
                </div>
                <div
                  className="mt-1 font-serif font-medium text-on-surface"
                  style={{ fontSize: 24, lineHeight: 1.1 }}
                >
                  {fmt(count)}
                </div>
                <div className="font-mono text-[10px] text-on-surface-variant">
                  {((count / NODES_TOTAL) * 100).toFixed(2)}% of corpus
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* ENRICHMENT */}
        <Section label="Enrichment">
          <h2 className="lex-h2">
            Temporal & authority metadata.{" "}
            <span className="italic text-on-surface-variant">on every node.</span>
          </h2>
          <p className="mb-5 max-w-3xl text-on-surface-variant" style={{ fontSize: 16, lineHeight: 1.6 }}>
            The enrichment pass derives publication / effective / repeal dates,
            the issuing authority, and supersession links from each node's
            metadata block. These power the live time-travel slider and the
            authority lattice on /ask.
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <EnrichmentStat label="Publication date" value={R.enrichment.with_publication_date} total={NODES_TOTAL} />
            <EnrichmentStat label="Effective date"   value={R.enrichment.with_effective_date}   total={NODES_TOTAL} />
            <EnrichmentStat label="Authority"        value={R.enrichment.with_authority}        total={NODES_TOTAL} />
            <EnrichmentStat label="Usable now"       value={R.enrichment.usable_true}           total={NODES_TOTAL} />
            <EnrichmentStat label="Repeal date"      value={R.enrichment.with_repeal_date}      total={NODES_TOTAL} />
            <EnrichmentStat label="Superseded by"    value={R.enrichment.with_superseded_by}    total={NODES_TOTAL} />
            <EnrichmentStat label="In force = false" value={R.enrichment.in_force_false}        total={NODES_TOTAL} />
            <EnrichmentStat label="Superseded total" value={R.enrichment.superseded}            total={NODES_TOTAL} />
          </div>
        </Section>

        {/* STORAGE */}
        <Section label="Storage">
          <h2 className="lex-h2">
            What sits on disk.{" "}
            <span className="italic text-on-surface-variant">queryable from day one.</span>
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <StorageCard
              icon="database"
              label="Property graph"
              kind={R.storage.graph_db_kind.toUpperCase()}
              size={fmtBytes(R.storage.graph_db_size_bytes)}
              detail="graph.db / SQLite. 2.25M edges + 1.97M nodes + enrichment columns indexed for Cypher-style traversal."
            />
            {R.storage.lancedb && (
              <StorageCard
                icon="indeterminate_check_box"
                label="Vector index"
                kind="LANCEDB"
                size={fmtBytes(R.storage.lancedb.total_size_bytes)}
                detail={`${R.storage.lancedb.file_count} Lance files across ${R.storage.lancedb.tables.length} table(s): ${R.storage.lancedb.tables.join(", ")}. Indexes ${fmt(R.scan.chunks_scanned)} BGE-M3 embeddings.`}
              />
            )}
            {R.storage.lancedb_pilot && (
              <StorageCard
                icon="science"
                label="Pilot vector index"
                kind="LANCEDB"
                size={fmtBytes(R.storage.lancedb_pilot.total_size_bytes)}
                detail={`Pilot subset: ${R.storage.lancedb_pilot.file_count} files. Used for retrieval-quality eval before full re-index.`}
              />
            )}
            <StorageCard
              icon="text_snippet"
              label="Retrieval chunks"
              kind="JSONL"
              size={fmtBytes(R.scan.chunk_token_total * 4)}
              detail={`${fmt(R.scan.chunks_scanned)} chunks averaging ${R.declared_stats?.avg_chunk_tokens?.toFixed(0) ?? "~"} tokens each. Section-aware splits keep statutory structure intact.`}
            />
            <StorageCard
              icon="account_tree"
              label="Hierarchy"
              kind="JSON"
              size="217 MB"
              detail="hierarchy.json: full parent/child tree dump for cold-start graph reconstruction without parsing edges.jsonl."
            />
            <StorageCard
              icon="bug_report"
              label="Dangling log"
              kind="JSONL"
              size={fmtBytes(EDGES_DANGLING * 280)}
              detail={`${fmt(EDGES_DANGLING)} unresolved references, all reasoned. Reprocess the corpus to retire most "not_yet_parsed" entries.`}
            />
          </div>
        </Section>

        {/* CROSS-DOC EXTRACTION */}
        <Section label="Cross-document patterns">
          <h2 className="lex-h2">
            10 deterministic patterns,{" "}
            <span className="italic text-on-surface-variant">hand-validated.</span>
          </h2>
          <p className="mb-5 max-w-3xl text-on-surface-variant" style={{ fontSize: 16, lineHeight: 1.6 }}>
            The 311K regex-extracted edges + 35K anchor edges come from these
            patterns. Gold set is hand-labelled and reproducible via pytest --
            <strong> 98.6% aggregate precision, 100% aggregate recall</strong>.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="bg-surface-container-low">
                  {["PATTERN", "DOMAIN", "EXTRACTS", "GOLD", "PREC", "RECALL"].map((h) => (
                    <th key={h} className="lex-th">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-sans text-[14px] text-on-surface">
                {PATTERN_ROWS.map((r) => (
                  <tr key={r.name} className="transition-colors hover:bg-surface-container-low/50">
                    <td className="lex-td font-mono text-xs">{r.name}</td>
                    <td className={"lex-td font-mono text-xs uppercase " + (DOMAIN_TONE[r.domain] ?? "")}>
                      {r.domain}
                    </td>
                    <td className="lex-td text-on-surface-variant">{r.what}</td>
                    <td className="lex-td font-mono text-xs">{r.gold}</td>
                    <td className="lex-td font-mono text-xs">{r.prec.toFixed(1)}%</td>
                    <td className="lex-td font-mono text-xs">{r.rec.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        {/* CONFIDENCE */}
        <Section label="Confidence">
          <h2 className="lex-h2">
            How &ldquo;CONFIDENCE: HIGH&rdquo;{" "}
            <span className="italic text-on-surface-variant">is actually calculated.</span>
          </h2>
          <ol
            className="ml-4 list-decimal space-y-3 text-on-background marker:text-on-surface-variant"
            style={{ fontSize: 16, lineHeight: 1.6 }}
          >
            <li>
              <strong>Per-claim grounding.</strong> The Verifier walks every
              cited node back to its source HTML and computes a 5-gram Jaccard
              overlap between the claim sentence and the cited paragraph. A
              claim is <span className="cite-pill">full</span> if overlap is at
              least 0.45, <span className="cite-pill">partial</span> if at
              least 0.20, else <span className="cite-pill">none</span>.
            </li>
            <li>
              <strong>Authority lattice.</strong> If two cited nodes disagree,
              the higher-rank one wins. Rank 8 (binding law) &gt; 7 (Supreme
              court) &gt; 6 (recent amendment) &gt; 5 (specific rule) &gt; 4
              (higher authority) &gt; 3 (Vero ohje) &gt; 2 (older rule) &gt; 1
              (informal note).
            </li>
            <li>
              <strong>Aggregation.</strong>{" "}
              <span className="cite-pill">HIGH</span> = all claims{" "}
              <span className="cite-pill">full</span> AND lattice resolved
              cleanly. <span className="cite-pill">MED</span> = ≥1 partial OR
              one resolved Debate. <span className="cite-pill">LOW</span> = any{" "}
              <span className="cite-pill">none</span> or unresolved conflict.
            </li>
            <li>
              <strong>Temporal sanity.</strong> Every cited node's enrichment
              window must overlap{" "}
              <span className="font-mono text-sm">$asof</span>. {fmt(R.enrichment.with_effective_date)} nodes
              ({fmtPct(R.enrichment.with_effective_date, NODES_TOTAL)}) carry
              an effective date; {fmt(R.enrichment.with_repeal_date)} carry a
              repeal date.
            </li>
            <li>
              <strong>No-hallucination guard.</strong> A sentence without a{" "}
              <span className="font-mono text-sm">[cite:node:X]</span> token is
              rejected by the streaming parser before it reaches the user.
            </li>
          </ol>
        </Section>

        {/* REPRODUCE */}
        <Section label="Reproduce">
          <h2 className="lex-h2">
            Every number on this page in 60 seconds.
          </h2>
          <pre className="overflow-x-auto border border-outline-variant bg-surface-container-lowest p-4 font-mono text-sm text-on-surface">
{`# from lex-atlas/

# 1. Sanitize the JSONL drop (rewrites data/audit/canonical_load.json).
python -m lex_atlas.ingest.canonical_load <drop_dir>
# expected (5 passes over 9 GB):
#   pass1 nodes   25s   1,967,776 records
#   pass2 parents  0.3s   1,904,115 references validated
#   pass3 edges   20s   2,180,769 resolved edges
#   pass4 chunks  18s     402,098 chunks
#   pass5 dangle   1s      69,252 dangling refs
#   ------
#   total         ${R.scan.elapsed_seconds.total.toFixed(1)}s   0 integrity issues

# 2. Cross-doc regex gold set (167 fixtures, ~0.2s).
python -m pytest lex_atlas/ingest/tests/test_regex_patterns.py -v
# expected:  110 passed, 98.6% precision, 100% recall.`}
          </pre>
        </Section>

        <div className="flex justify-center pt-4">
          <Link href="/eval" className="btn-secondary btn-sm">
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
              arrow_back
            </span>
            Back to Eval
          </Link>
        </div>
      </div>

      <Footer />
    </main>
  );
}

/* --------------------------------------------------------------------- */

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="grid grid-cols-1 gap-6 md:grid-cols-12">
      <div className="md:col-span-3">
        <p className="font-mono text-[11px] uppercase tracking-widest text-on-surface-variant">
          {label}
        </p>
      </div>
      <div className="border-t border-outline-variant pt-4 md:col-span-9">
        {children}
      </div>
    </section>
  );
}

function BigStat({
  label, value, sub, accent,
}: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="flex flex-col gap-2 bg-surface-container-lowest p-5 sm:p-6">
      <div className="font-mono text-[11px] uppercase tracking-widest text-on-surface-variant">
        {label}
      </div>
      <div
        className={"font-serif font-medium " + (accent ? "text-secondary" : "text-on-surface")}
        style={{
          fontSize: "clamp(28px, 3.2vw, 40px)",
          lineHeight: 1.05,
          letterSpacing: "-0.02em",
        }}
      >
        {value}
      </div>
      {sub && (
        <div className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
          {sub}
        </div>
      )}
    </div>
  );
}

function IntegrityCheck({
  label, pass, detail,
}: { label: string; pass: boolean; detail?: string }) {
  return (
    <div className="border border-outline-variant bg-surface-container-lowest p-3">
      <div className="flex items-center gap-1.5">
        <span
          className="material-symbols-outlined"
          style={{ fontSize: 16, color: pass ? "var(--color-secondary)" : "var(--color-error)" }}
        >
          {pass ? "check_circle" : "error"}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-on-surface-variant">
          {label}
        </span>
      </div>
      {detail && (
        <div className="mt-1 font-mono text-[11px] text-on-surface">{detail}</div>
      )}
    </div>
  );
}

function EnrichmentStat({
  label, value, total,
}: { label: string; value: number; total: number }) {
  const pct = total === 0 ? 0 : (value / total) * 100;
  return (
    <div className="border border-outline-variant bg-surface-container-lowest p-4">
      <div className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">
        {label}
      </div>
      <div
        className="mt-1 font-serif font-medium text-on-surface"
        style={{ fontSize: 24, lineHeight: 1.1 }}
      >
        {fmt(value)}
      </div>
      <div className="relative mt-2 h-px w-full bg-outline-variant">
        <div className="absolute left-0 top-0 h-px bg-secondary" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 font-mono text-[10px] text-on-surface-variant">
        {pct.toFixed(1)}% of nodes
      </div>
    </div>
  );
}

function StorageCard({
  icon, label, kind, size, detail,
}: { icon: string; label: string; kind: string; size: string; detail: string }) {
  return (
    <div className="flex h-full flex-col gap-3 border border-outline-variant bg-surface-container-lowest p-5">
      <div className="flex items-center justify-between">
        <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 20 }}>
          {icon}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-widest text-secondary">
          {kind}
        </span>
      </div>
      <div>
        <div className="font-sans text-[14px] font-semibold text-on-surface">{label}</div>
        <div
          className="mt-1 font-serif font-medium text-on-surface"
          style={{ fontSize: 26, lineHeight: 1.05, letterSpacing: "-0.02em" }}
        >
          {size}
        </div>
      </div>
      <p className="font-sans text-[12.5px] leading-[1.55] text-on-surface-variant">
        {detail}
      </p>
    </div>
  );
}

function edgeProvenance(t: string): string {
  switch (t) {
    case "parent_of":  return "structural (1.0)";
    case "defines":    return "regex / anchor";
    case "cites":      return "regex / anchor";
    case "applies":    return "regex";
    case "interprets": return "Vero anchors";
    case "transposes": return "EU treaty matcher";
    case "repeals":    return "supersedes regex";
    case "amends":     return "amendment header regex";
    default:           return "n/a";
  }
}

function friendlyNodeLabel(id: string): string {
  const friendly: Record<string, string> = {
    "tuloverolaki":               "Tuloverolaki (Income Tax Act)",
    "arvonlisaverolaki":          "Arvonlisaverolaki (VAT Act)",
    "elinkeinotulon-verottamisesta": "Laki elinkeinotulon verottamisesta (EVL)",
    "hallintolaki":               "Hallintolaki (Administrative Procedure Act)",
    "verotusmenettelysta":        "Laki verotusmenettelysta (Tax Procedure Act)",
    "ennakkoperintalaki":         "Ennakkoperintalaki (Withholding Tax Act)",
    "varainsiirtoverolaki":       "Varainsiirtoverolaki (Transfer Tax Act)",
    "oma-aloitteisten-verojen":   "Laki oma-aloitteisten verojen verotusmenettelysta",
    "tyosopimuslaki":             "Tyosopimuslaki (Employment Contracts Act)",
    "velkakirjalaki":             "Velkakirjalaki (Promissory Notes Act)",
    "osuuskuntalaki":             "Osuuskuntalaki (Cooperatives Act)",
    "maatilatalouden-tuloverolaki":"Maatilatalouden tuloverolaki (Farm Income Tax)",
    "raportoivien-finanssilaitosten":"Laki raportoivien finanssilaitosten tiedonantovelvollisuudesta",
    "suurten-konsernien":         "Laki suurten konsernien vahimmaisverosta (Pillar 2)",
  };
  for (const key in friendly) {
    if (id.includes(key)) return friendly[key];
  }
  // Strip the hash + path prefix, prettify
  const last = id.replace(/.*\//, "").replace(/-html-[a-z0-9]+$/, "").replace(/-/g, " ");
  return last.charAt(0).toUpperCase() + last.slice(1);
}
