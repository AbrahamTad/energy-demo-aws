import { expect, it, vi } from "vitest";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { sharedInMemoryStorage } from "aws-amplify/utils";
vi.mock("aws-amplify/auth/cognito", () => ({
  cognitoUserPoolsTokenProvider: { setKeyValueStorage: vi.fn() },
}));
it("configures the SDK token provider to use memory, never browser storage", async () => {
  await import("./client");
  expect(cognitoUserPoolsTokenProvider.setKeyValueStorage).toHaveBeenCalledWith(
    sharedInMemoryStorage,
  );
});
