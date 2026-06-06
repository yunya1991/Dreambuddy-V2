import fs from 'fs';
import path from 'path';
import type { OrgTreeData } from './org-types';
import { applyStatusInference } from './status-inference';

const DATA_DIR = path.join(process.cwd(), 'data');
const EMPTY_ORG_TREE_NAME = 'Dream Product Hub';

function createEmptyOrgTreeData(): OrgTreeData {
  return {
    company: {
      name: EMPTY_ORG_TREE_NAME,
      departments: [],
      total_nodes: 0,
    },
    stats: {
      total_skills: 0,
      in_org_tree: 0,
      utility: 0,
      unclassified: 0,
      has_frontmatter: 0,
      missing_frontmatter: [],
    },
    all_skills: {},
  };
}

function readJsonFile<T>(filePath: string, fallback: T): T {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(raw) as T;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return fallback;
    }

    throw error;
  }
}

/** Get raw org tree data */
export function getOrgTreeData(): OrgTreeData {
  const filePath = path.join(DATA_DIR, 'org_tree.json');
  return readJsonFile(filePath, createEmptyOrgTreeData());
}

/** Get org tree with inferred node status */
export function getOrgTreeWithStatus(): OrgTreeData {
  const orgData = getOrgTreeData();

  // Load artifacts for status inference
  const artifactsPath = path.join(DATA_DIR, 'artifacts_index.json');
  const artifacts = readJsonFile(artifactsPath, [] as {
    chain_phase: string;
    status: string;
    date: string;
  }[]);

  return applyStatusInference(orgData, artifacts);
}
