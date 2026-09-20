/**
 * The two things you type in: a day's calories, and a weigh-in.
 *
 * Both go to the Python server, which applies the same checks the command line does and
 * answers with the same sentences. A refusal comes back as a readable message rather
 * than an exception, so the form can show it next to the field.
 *
 * `status` is kept because the weigh-in endpoint uses one code for a specific meaning:
 * 409 says "this is far from your last weigh-in", and the form responds by offering to
 * send it again with `force`.
 */

export type WriteResult = {
  ok: boolean;
  status: number;
  message: string;
};

export type IntakeRequest = {
  day: string;
  kilocalories: number;
  note?: string;
};

export type WeighRequest = {
  day: string;
  kilograms: number;
  fat_percent?: number;
  force?: boolean;
};

export async function postIntake(request: IntakeRequest): Promise<WriteResult> {
  return post("/api/intake", request, (body) => {
    const replaced = body.replaced as number | null;

    if (replaced !== null) {
      return `Replaced ${replaced} kcal with ${request.kilocalories} kcal for ${request.day}.`;
    }

    return `Recorded ${request.kilocalories} kcal for ${request.day}.`;
  });
}

export async function postWeighing(request: WeighRequest): Promise<WriteResult> {
  return post("/api/weigh", request, (body) => {
    const change = body.change_since_previous as { kilograms: number; days: number } | null;
    let sentence = `Recorded ${request.kilograms} kg for ${request.day}.`;

    if (change !== null) {
      const sign = change.kilograms > 0 ? "+" : "";
      sentence = `${sentence} ${sign}${change.kilograms.toFixed(1)} kg over ${change.days} day(s).`;
    }

    return sentence;
  });
}

async function post(
  url: string,
  body: unknown,
  describeSuccess: (responseBody: Record<string, unknown>) => string,
): Promise<WriteResult> {
  let response: Response;

  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return {
      ok: false,
      status: 0,
      message: "Could not reach the API. Is uvicorn running on port 8000?",
    };
  }

  // Same reasoning as in loadDays: a lapsed session is not an error to report, it is a
  // reason to sign in again. Done before reading the body, which for a 401 from the edge
  // is a fixed sentence rather than anything worth showing.
  if (response.status === 401) {
    const next = encodeURIComponent(window.location.pathname + window.location.hash);
    window.location.replace(`/login.html?next=${next}`);

    return { ok: false, status: 401, message: "Signing in again…" };
  }

  const responseBody = (await response.json().catch(() => ({}))) as Record<string, unknown>;

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      message: describeFailure(responseBody, response.status),
    };
  }

  return { ok: true, status: response.status, message: describeSuccess(responseBody) };
}

/**
 * FastAPI puts our sentence in `detail` as a string. Its OWN validation errors -- a
 * missing field, a word where a number should be -- put a list of objects there instead,
 * so both shapes are handled.
 */
function describeFailure(responseBody: Record<string, unknown>, status: number): string {
  const detail = responseBody.detail;

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const where = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "";
    return `${where}: ${first.msg ?? "invalid"}`;
  }

  return `The API refused the request (HTTP ${status}).`;
}


/**
 * End this browser's session and return to the login page.
 *
 * Only this browser. Signing every device out at once means rotating the signing secret,
 * which is the emergency lever rather than the everyday one -- see `backend/api/auth.py`.
 *
 * The redirect happens whatever the server answers. If the request failed, the cookie may
 * still be set, but the login page is where you want to be either way, and it will bounce
 * you straight back in if the session turned out to still be good.
 */
export async function signOut(): Promise<void> {
  try {
    await fetch("/api/logout", { method: "POST" });
  } catch {
    // Offline, or the API is down. Go to the login page regardless.
  }

  window.location.replace("/login.html");
}
