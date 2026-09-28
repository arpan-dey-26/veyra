import { fieldErrors, isProblem, type ProblemDetails } from "@veyra/api-client";

export interface ApiFailure {
  problem: ProblemDetails;
  fields: Record<string, string>;
  message: string;
}

const NETWORK_PROBLEM: ProblemDetails = {
  type: "about:blank",
  title: "Can't reach VEYRA",
  status: 0,
  code: "network_error",
  detail: "Check your connection and try again.",
  request_id: null,
};

/** Normalise any failed call (problem body, unexpected body or network error). */
export function toFailure(error: unknown, response?: Response): ApiFailure {
  let problem: ProblemDetails;
  if (isProblem(error)) {
    problem = error;
  } else if (response) {
    problem = {
      type: "about:blank",
      title: "Something went wrong",
      status: response.status,
      code: "unexpected_response",
      detail: "Please try again in a moment.",
      request_id: response.headers.get("x-request-id"),
    };
  } else {
    problem = NETWORK_PROBLEM;
  }
  const fields = fieldErrors(problem);
  const message =
    problem.code === "validation_error" && Object.keys(fields).length > 0
      ? "Please correct the highlighted fields."
      : problem.detail || problem.title;
  return { problem, fields, message };
}

export const networkFailure = (): ApiFailure => toFailure(undefined);
