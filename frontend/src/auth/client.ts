import { Amplify } from "aws-amplify";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { sharedInMemoryStorage } from "aws-amplify/utils";
import { readCognitoConfig } from "./config";

export const cognitoConfig = readCognitoConfig(
  import.meta.env.VITE_COGNITO_USER_POOL_ID,
  import.meta.env.VITE_COGNITO_CLIENT_ID,
);
if (cognitoConfig) {
  Amplify.configure({
    Auth: { Cognito: { ...cognitoConfig, loginWith: { email: true } } },
  });
  // Amplify's default is localStorage. Override before any auth operation.
  // Access, ID and refresh tokens live only in this page's memory.
  cognitoUserPoolsTokenProvider.setKeyValueStorage(sharedInMemoryStorage);
}
export { sharedInMemoryStorage };

export function authError(error: unknown): string {
  const name = error instanceof Error ? error.name : "";
  const messages: Record<string, string> = {
    NotAuthorizedException:
      "Unable to sign in. Check your details, or reset your password.",
    UserNotFoundException:
      "Unable to sign in. Check your details, or reset your password.",
    UsernameExistsException:
      "Unable to create this account. Try signing in or resetting your password.",
    InvalidPasswordException:
      "Use at least 12 characters with uppercase, lowercase, a number, and a symbol.",
    CodeMismatchException:
      "That code is incorrect. Please check it and try again.",
    ExpiredCodeException: "That code has expired. Request a new code.",
    LimitExceededException:
      "Too many attempts. Please wait before trying again.",
    TooManyRequestsException:
      "Too many requests. Please wait before trying again.",
    UserNotConfirmedException: "Verify your email before signing in.",
    NetworkError:
      "Cannot reach the account service. Check your connection and try again.",
  };
  return (
    messages[name] ??
    "The account service could not complete your request. Please try again."
  );
}

export function passwordError(password: string) {
  return password.length < 12 ||
    password.length > 128 ||
    !/[a-z]/.test(password) ||
    !/[A-Z]/.test(password) ||
    !/[0-9]/.test(password) ||
    !/[^A-Za-z0-9\s]/.test(password)
    ? "Use 12–128 characters with uppercase, lowercase, a number, and a symbol."
    : "";
}

// A stable Cognito sub is the ownership key for a future database. Never trust
// a client-submitted subject for authorization; validate the access JWT in AWS.
export type UserProfile = {
  subject: string;
  email: string;
  emailVerified: boolean;
  name: string;
};
