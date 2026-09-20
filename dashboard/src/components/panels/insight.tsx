import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/surface";
import { loadInsight, type InsightAnswer } from "@/data/insight";

/**
 * A few sentences on what the numbers are doing.
 *
 * WHAT IT IS ALLOWED TO BE
 * ------------------------
 * The model never sees a raw reading and never does arithmetic. It is handed a fact sheet
 * this project computed, and every number it writes back is checked against that sheet
 * before anything reaches this component. A reading containing an invented figure is
 * discarded on the server, and this panel says so plainly rather than hiding it.
 *
 * That is why the panel can sit on a health dashboard at all. It is not "the AI might be
 * wrong, be careful" -- it is that the one thing a model is dangerous at here, producing
 * a number, has been made structurally impossible.
 *
 * It loads on its own, after the charts. A model call takes a second or two and must
 * never be the reason a chart is late.
 */
export function InsightPanel() {
  const [answer, setAnswer] = useState<InsightAnswer | null>(null);

  useEffect(() => {
    loadInsight()
      .then(setAnswer)
      .catch(() => setAnswer(null));
  }, []);

  return (
    <Panel>
      <PanelHeader
        icon={Sparkles}
        title="Reading"
        tone="ion"
        note="An interpretation of the figures above. Every number is checked against your data before it appears here."
      />
      <PanelBody>
        {answer === null && <p className="font-mono text-xs text-hull-400">reading the numbers…</p>}

        {answer?.status === "ready" && answer.reading !== null && (
          <>
            {answer.reading.headline !== "" && (
              <p className="mb-3 text-base font-medium leading-snug text-white">
                {answer.reading.headline}
              </p>
            )}

            <ul className="flex flex-col gap-2.5">
              {answer.reading.observations.map((one) => (
                <li key={one} className="flex gap-2.5 text-sm leading-relaxed text-hull-200">
                  <span className="mt-2 size-1 shrink-0 bg-ion-400" aria-hidden="true" />
                  <span>{one}</span>
                </li>
              ))}
            </ul>

            <p className="mt-4 border-t border-hull-700 pt-2.5 text-[0.66rem] text-hull-500">
              Rewritten whenever your numbers change.
            </p>
          </>
        )}

        {answer?.status === "unavailable" && (
          <p className="text-sm leading-relaxed text-hull-300">
            No reading available right now.
          </p>
        )}

        {answer?.status === "rejected" && (
          <>
            <p className="text-sm leading-relaxed text-hull-100">
              A reading was written and discarded. It contained a figure that is not in your
              data, so none of it is shown.
            </p>
          </>
        )}
      </PanelBody>
    </Panel>
  );
}
