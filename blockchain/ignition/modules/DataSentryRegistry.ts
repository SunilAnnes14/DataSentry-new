import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

/**
 * Deploys DataSentryRegistry with the deployer as coordinator.
 * Participants are registered by the backend (coordinator wallet) on startup,
 * so the module stays network-agnostic.
 */
export default buildModule("DataSentryRegistryModule", (m) => {
  const registry = m.contract("DataSentryRegistry");
  return { registry };
});
