import path from 'node:path';
import { buildArtifactRelations, groupRelationsByPhase } from "./artifact-relations.ts";
import { ContentRepository } from './content.repository.ts';

const DEFAULT_ARTIFACTS_ROOT = path.join(
  process.env.HOME || '/Users/zhangjiangtao',
  '.workbuddy/artifacts',
);

function resolveArtifactsRoot(): string {
  return process.env.WORKBUDDY_ARTIFACTS_ROOT || DEFAULT_ARTIFACTS_ROOT;
}

let singletonRoot = '';
let singletonRepo: ContentRepository | null = null;

function getRepository(): ContentRepository {
  const root = resolveArtifactsRoot();
  if (!singletonRepo || singletonRoot !== root) {
    singletonRoot = root;
    singletonRepo = new ContentRepository(root);
  }
  return singletonRepo;
}

export function getArtifactsIndex() {
  return getRepository().getArtifactsIndex();
}

export function getArtifactsData() {
  return getRepository().getArtifactsData();
}

export function invalidateCache() {
  singletonRoot = '';
  singletonRepo = null;
}

export function getArtifactBySlug(slug: string) {
  return getRepository().getArtifactDetailBySlug(slug);
}

export function getArtifactRelations() {
  return buildArtifactRelations(getRepository().getArtifactsIndex());
}

export function getChainPhaseArtifacts(limitPerPhase = 3) {
  return groupRelationsByPhase(getArtifactRelations(), limitPerPhase);
}

export function getAllSlugs(): string[] {
  return getRepository()
    .getArtifactsIndex()
    .map((item) => `${item.category}/${item.artifactId}`);
}
