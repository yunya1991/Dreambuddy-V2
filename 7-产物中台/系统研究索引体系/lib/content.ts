/**
 * Content module re-export for Next.js compatibility.
 * All functions are server-side only (use fs).
 */
export {
  getArtifactsIndex,
  getArtifactsData,
  getArtifactBySlug,
  getArtifactRelations,
  getChainPhaseArtifacts,
  getAllSlugs,
} from './content.server';
