import { describe, expect, it } from "vitest";
import {
  productionCognitoConfig,
  readCognitoConfig,
  resolveBuildCognitoConfig,
} from "./config";
import { safeReturnPath } from "./context";
import { passwordError } from "./client";
describe("authentication boundaries", () => {
  it("uses the deployed public ID pair in AWS builds when CI variables are empty", () => {
    expect(resolveBuildCognitoConfig("aws", "", "")).toEqual({
      userPoolId: "eu-north-1_6m60ePWS0",
      userPoolClientId: "796jkcsk4dc5scoc77r8ejies7",
    });
    expect(
      resolveBuildCognitoConfig(
        "aws",
        productionCognitoConfig.userPoolId,
        productionCognitoConfig.userPoolClientId,
      ),
    ).toEqual(productionCognitoConfig);
  });
  it("rejects partial and conflicting AWS overrides rather than mixing identities", () => {
    expect(() =>
      resolveBuildCognitoConfig("aws", productionCognitoConfig.userPoolId, ""),
    ).toThrow();
    expect(() =>
      resolveBuildCognitoConfig(
        "aws",
        "",
        productionCognitoConfig.userPoolClientId,
      ),
    ).toThrow();
    expect(() =>
      resolveBuildCognitoConfig("aws", "eu-north-1_Other", "otherclient"),
    ).toThrow(/must match the deployed/);
    expect(() =>
      resolveBuildCognitoConfig(
        "aws",
        productionCognitoConfig.userPoolId,
        "otherclient",
      ),
    ).toThrow(/must match the deployed/);
  });
  it("keeps local development configuration explicit", () => {
    expect(resolveBuildCognitoConfig("development")).toBeNull();
    expect(
      resolveBuildCognitoConfig(
        "development",
        "eu-north-1_Local",
        "localclient",
      ),
    ).toEqual({
      userPoolId: "eu-north-1_Local",
      userPoolClientId: "localclient",
    });
  });
  it("requires a complete regional public configuration", () => {
    expect(readCognitoConfig()).toBeNull();
    expect(() => readCognitoConfig("eu-north-1_Fixture", "")).toThrow();
    expect(() => readCognitoConfig("us-east-1_Fixture", "client")).toThrow();
    expect(readCognitoConfig("eu-north-1_Fixture", "client")).toEqual({
      userPoolId: "eu-north-1_Fixture",
      userPoolClientId: "client",
    });
  });
  it("accepts only local protected return routes", () => {
    for (const value of [
      "https://example.invalid",
      "//example.invalid",
      "/login",
      undefined,
    ])
      expect(safeReturnPath(value)).toBe("/dashboard");
    expect(safeReturnPath("/profile")).toBe("/profile");
  });
  it("enforces the pool password policy", () => {
    expect(passwordError("short")).not.toBe("");
    expect(passwordError("longbutmissingtypes")).not.toBe("");
    expect(passwordError("Valid-Test-1234")).toBe("");
  });
});
