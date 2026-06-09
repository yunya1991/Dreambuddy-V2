import { loadConfig, resolveRepoRoot } from "./config.js";
import { createHubServer } from "./server.js";

const repoRoot = resolveRepoRoot();
const config = loadConfig(repoRoot);
const server = createHubServer();

server.listen(config.server.port, config.server.host, () => {
  console.log(`artifact-hub-v2 listening on http://${config.server.host}:${config.server.port}`);
});
