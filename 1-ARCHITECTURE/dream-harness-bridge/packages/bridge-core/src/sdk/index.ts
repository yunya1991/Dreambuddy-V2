/**
 * dream-harness-bridge bridge-core SDK
 *
 * F-01: 契约版本化
 * F-02: 协议级硬约束
 * F-07: 双端 SDK 抽象
 */

export {
  createProtocolClient,
  ProtocolHandshakeError,
  CURRENT_SCHEMA_VERSION,
} from "./protocol-client";
export type {
  IPCRequest,
  IPCResponse,
  HandshakeResult,
  ProtocolClientOptions,
} from "./protocol-client";

export { startPythonIPCServer, stopPythonIPCServer, isAlive, checkHeartbeat } from "./python-ipc";
export type { StartPythonIPCServerOptions } from "./python-ipc";
