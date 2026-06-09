import type { ArtifactRelation } from "@/lib/types";

export function findArtifactChainRelation(
  artifactId: string,
  relations: ArtifactRelation[],
): ArtifactRelation | undefined {
  return relations.find((item) => item.artifactId === artifactId);
}
