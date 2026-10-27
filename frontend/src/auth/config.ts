export type CognitoConfig = { userPoolId: string; userPoolClientId: string };

// Public identifiers, not credentials. This pool/client are provisioned in the
// separate identity root; frontend builds never read Terraform state or use AWS
// credentials. Keep the pair together when intentionally replacing identity.
export const productionCognitoConfig: CognitoConfig = {
  userPoolId: "eu-north-1_6m60ePWS0",
  userPoolClientId: "796jkcsk4dc5scoc77r8ejies7",
};

export function readCognitoConfig(
  poolId = "",
  clientId = "",
): CognitoConfig | null {
  if (!poolId && !clientId) return null;
  if (
    !/^eu-north-1_[A-Za-z0-9]+$/.test(poolId) ||
    !/^[a-z0-9]{1,128}$/.test(clientId)
  ) {
    throw new Error(
      "Set both Cognito public IDs: a eu-north-1 user pool and its SPA client. Do not supply client secrets.",
    );
  }
  return { userPoolId: poolId, userPoolClientId: clientId };
}

export function resolveBuildCognitoConfig(
  mode: string,
  poolId = "",
  clientId = "",
): CognitoConfig | null {
  const configured = readCognitoConfig(poolId, clientId);
  if (mode !== "aws") return configured;
  if (
    configured &&
    (configured.userPoolId !== productionCognitoConfig.userPoolId ||
      configured.userPoolClientId !== productionCognitoConfig.userPoolClientId)
  ) {
    throw new Error(
      "AWS Cognito overrides must match the deployed pool/client in src/auth/config.ts. Check COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID repository variables.",
    );
  }
  return productionCognitoConfig;
}
