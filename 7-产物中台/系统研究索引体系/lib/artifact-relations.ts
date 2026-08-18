import type {
  ArtifactRelation,
  CanonicalArtifactIndex,
  ChainPhaseArtifacts,
} from "./types.ts";

export function buildArtifactRelations(
  index: CanonicalArtifactIndex[],
): ArtifactRelation[] {
  return index
    .filter((item) => item.chainPhase)
    .map((item) => ({
      artifactId: item.artifactId,
      chainPhase: item.chainPhase,
      feedHref: item.detailUrl,
      chainHref: `/chain?phase=${encodeURIComponent(item.chainPhase)}&artifact=${encodeURIComponent(item.artifactId)}`,
      nodeId: item.chainPhase,
      title: item.title,
      date: item.date,
    }));
}

export function groupRelationsByPhase(
  relations: ArtifactRelation[],
  limitPerPhase = 3,
): ChainPhaseArtifacts {
  const grouped: ChainPhaseArtifacts = {};

  for (const relation of relations) {
    if (!grouped[relation.chainPhase]) {
      grouped[relation.chainPhase] = [];
    }

    grouped[relation.chainPhase].push(relation);
  }

  for (const phase of Object.keys(grouped)) {
    grouped[phase] = grouped[phase]
      .sort((a, b) => b.date.localeCompare(a.date))
      .slice(0, limitPerPhase);
  }

  return grouped;
}
