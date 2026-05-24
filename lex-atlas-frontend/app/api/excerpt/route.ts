/**
 * /api/excerpt — citation drawer payload.
 *
 * Tries the Python sidecar first; falls back to a Next.js-side fixture for
 * the Q4 cited nodes so the demo works even when the sidecar is down.
 */

import type { NextRequest } from "next/server";
import type { ExcerptResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

const FIXTURES: Record<string, ExcerptResponse> = {
  "work:avainhenkilolaki": {
    nodeId: "work:avainhenkilolaki",
    sourceUrl: "https://www.finlex.fi/fi/laki/ajantasa/1995/19951551",
    publisher: "finlex",
    docTitle: "Laki ulkomailta tulevan palkansaajan lähdeverosta",
    excerptHtml:
      'Tällä lailla säädetään ulkomailta tulevan palkansaajan ' +
      '<mark class="claim-match">lähdeverosta</mark> ' +
      '(<strong>1551/1995</strong>, avainhenkilölaki).',
    contextHtml: "",
    lang: "fi",
  },
  "ctv:avh:§3@2026-01-01": {
    nodeId: "ctv:avh:§3@2026-01-01",
    sourceUrl:
      "https://www.vero.fi/syventavat-vero-ohjeet/ohje-hakusivu/48000/rajoitetusti_verovelvollisen_tulon_ja_avainhenkilon",
    publisher: "vero",
    docTitle:
      "Rajoitetusti verovelvollisen tulon ja avainhenkilön lähdeverotusmenettely",
    excerptHtml:
      'Suomeen yli kuudeksi kuukaudeksi tuleva yleisesti verovelvollinen ' +
      'henkilö voi eräissä tapauksissa maksaa palkkatulostaan progressiivisen ' +
      'veron sijasta <mark class="claim-match">25 prosentin</mark> ' +
      'suuruista palkkatulon lähdeveroa (avainhenkilölain 3 §). ' +
      'Päivitetty 8.1.2026 avainhenkilölain 2 §:n ja 3 §:n muutosten vuoksi.',
    contextHtml: "",
    lang: "fi",
    tValid: "2026-01-01",
    tInvalid: null,
    docketNumber: "VH/0001/00.01.00/2026",
  },
  "ctv:avh:§3@2020-01-01": {
    nodeId: "ctv:avh:§3@2020-01-01",
    sourceUrl:
      "https://www.vero.fi/syventavat-vero-ohjeet/kannanotot/avainhenkiloeltae-perittaevae-laehdevero-vuodesta-2020-alkaen/",
    publisher: "vero",
    docTitle:
      "Avainhenkilöltä perittävä lähdevero vuodesta 2020 alkaen",
    excerptHtml:
      'Vuodesta 2020 alkaen avainhenkilölain 3 §:n mukaan avainhenkilöltä ' +
      'perittävä lähdevero on <mark class="claim-match">32 %</mark>. ' +
      'Alennettua 32 prosentin lähdeveroa sovelletaan palkkaan, joka maksetaan ' +
      '1 päivänä tammikuuta 2020 tai sen jälkeen.',
    contextHtml: "",
    lang: "fi",
    tValid: "2020-01-01",
    tInvalid: "2025-12-31",
  },
  "comp:avh:§4": {
    nodeId: "comp:avh:§4",
    sourceUrl: "https://www.finlex.fi/fi/laki/ajantasa/1995/19951551#L1P4",
    publisher: "finlex",
    docTitle: "Avainhenkilölaki 4 §: Hakemus ja päätös",
    excerptHtml:
      'Avainhenkilölle annettavan verokortin voimassaoloajaksi merkitään ' +
      'hakemuksella ilmoitettu työskentelyaika Suomessa, kuitenkin enintään ' +
      '<mark class="claim-match">84 kuukautta</mark> työskentelyn alusta lukien ' +
      '(2026 alkaen; aiemmin 48 kuukautta).',
    contextHtml: "",
    lang: "fi",
  },
};

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const nodeId = url.searchParams.get("node_id");
  if (!nodeId) {
    return new Response("missing node_id", { status: 400 });
  }

  // 1. Try the Python sidecar first (real backend, has the full excerpt index)
  const sidecar = process.env.AGENT_SIDECAR_URL ?? "http://localhost:8000";
  try {
    const r = await fetch(`${sidecar}/excerpt?node_id=${encodeURIComponent(nodeId)}`, {
      signal: AbortSignal.timeout(2000),
    });
    if (r.ok) {
      const data = await r.json();
      return Response.json(data);
    }
  } catch {
    // sidecar unreachable / timed out -> fall through
  }

  // 2. Try the hand-written fixture map (Q4 + Debate demo nodes)
  const fixture = FIXTURES[nodeId];
  if (fixture) {
    return Response.json(fixture);
  }

  // 3. Last-resort fallback: synthesize a useful payload from the node id.
  //
  // Real Lex Atlas node ids look like:
  //   finlex/laki/finlex-laki-ennakkoperintalaki-1-html-c4e849e0/c1/s30a
  //    ^^^^^^ ^^^^ ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ ^^^ ^^^^
  //   source subcorpus law-slug                                       anchor
  //
  // We extract the slug, prettify the title from it, and link to the
  // canonical Finlex / Vero / KHO page. The popover and Inspector still
  // render with a real source URL and a sensible title - they just say
  // "Detailed excerpt not yet cached on this build" inline instead of a
  // 404 hard-failure.
  return Response.json(synthesizeExcerpt(nodeId));
}

/**
 * Synthesize an ExcerptResponse from a node id so the UI never 404s.
 */
function synthesizeExcerpt(nodeId: string): ExcerptResponse {
  const parts = nodeId.split("/");
  // Pure concept ids (e.g. "concept:avainhenkilo") get a stub.
  if (parts.length < 3 || nodeId.startsWith("concept:")) {
    return {
      nodeId,
      sourceUrl: "https://www.finlex.fi/",
      publisher: "finlex",
      docTitle: prettify(nodeId),
      excerptHtml:
        '<em>Detailed excerpt not yet cached on this build of the index.</em> ' +
        'The orbit still grounded its citation on this node via the typed graph.',
      contextHtml: "",
      lang: "fi",
    };
  }

  const source = parts[0]; // finlex | vero | kho
  const subcorpus = parts[1]; // laki | asetus | kho | vero_ohje | ...
  const slugWithHash = parts[2]; // finlex-laki-<slug>-html-<hash8>
  const anchor = parts.slice(3).join("/"); // c1/s30a/m2 etc, may be empty

  const publisher: ExcerptResponse["publisher"] =
    source === "vero" ? "vero" : source === "kho" ? "finlex" : "finlex";

  // Strip leading "finlex-laki-" / "vero-syventavat-..." prefix to get the
  // human-readable slug, then turn dashes into spaces and capitalise.
  const slugBare = slugWithHash
    .replace(/^finlex-(?:laki|asetus|kho|laki_skk|asetus_skk|treaty)-/, "")
    .replace(/-html-[0-9a-f]{6,}$/i, "")
    .replace(/^vero-syventavat-vero-ohjeet-/, "")
    .replace(/^vero-syventavat-/, "");
  const title = prettify(slugBare);

  // Best-effort canonical URL
  let sourceUrl = "https://www.finlex.fi/";
  if (source === "finlex" && (subcorpus === "laki" || subcorpus === "asetus")) {
    sourceUrl = `https://www.finlex.fi/fi/laki/ajantasa/?search%5Btype%5D=pika&search%5Bpika%5D=${encodeURIComponent(slugBare.split("-").slice(0, 4).join(" "))}`;
  } else if (source === "vero") {
    sourceUrl = `https://www.vero.fi/syventavat-vero-ohjeet/`;
  } else if (source === "kho") {
    sourceUrl = `https://www.finlex.fi/fi/oikeus/kho/`;
  }

  const anchorPretty = anchor ? ` (${formatAnchor(anchor)})` : "";

  return {
    nodeId,
    sourceUrl,
    publisher,
    docTitle: `${title}${anchorPretty}`,
    excerptHtml:
      '<em>Detailed excerpt not yet cached for this node on this build.</em><br/>' +
      '<span style="font-family:var(--font-mono);font-size:11px;color:#76330b">' +
      escapeHtml(nodeId) +
      "</span><br/>" +
      'Open the source link above to read the canonical text on ' +
      (source === "vero" ? "vero.fi" : "finlex.fi") +
      ".",
    contextHtml: "",
    lang: "fi",
  };
}

function prettify(s: string): string {
  return s
    .replace(/[-_]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/(?:^|\s)(\p{L})/gu, (m) => m.toUpperCase());
}

function formatAnchor(a: string): string {
  // c1/s30a/m2 -> "§ 30a mom 2"
  return a
    .split("/")
    .map((part) => {
      if (/^c\d+$/.test(part)) return `chap. ${part.slice(1)}`;
      if (/^s/.test(part)) return `§ ${part.slice(1)}`;
      if (/^m\d+$/.test(part)) return `mom. ${part.slice(1)}`;
      if (/^i\d+$/.test(part)) return `item ${part.slice(1)}`;
      if (/^p\d+$/.test(part)) return `para. ${part.slice(1)}`;
      return part;
    })
    .join(" ");
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
