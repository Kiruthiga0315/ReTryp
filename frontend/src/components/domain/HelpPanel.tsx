import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/client";
import { SlideOver } from "../ui/Dialog";
import { Icon } from "../ui/Icon";
import { InlineNote } from "../ui/States";
import type { RecoveryPlan } from "../../api/types";

const PROMPTS = [
  { value: "why_recommended", label: "Why was this recommended?" },
  { value: "cheaper", label: "Show cheaper alternatives" },
  { value: "do_nothing", label: "What if I don't change?" },
  { value: "connection", label: "Will I still make my connection?" },
  { value: "compensation", label: "Am I due compensation?" },
];

/** Small, secondary help surface reached from a plan card. Deliberately not
 *  the main interface. */
export function HelpPanel({
  open,
  onClose,
  tripId,
  plan,
}: {
  open: boolean;
  onClose: () => void;
  tripId: string | null;
  plan: RecoveryPlan | null;
}) {
  const [answers, setAnswers] = useState<Record<string, { answer: string; source: string }>>({});
  const [activePrompt, setActivePrompt] = useState<string | null>(null);

  const ask = useMutation({
    mutationFn: (topic: string) =>
      api.help({ trip_id: tripId ?? "", plan_id: plan?.plan_id ?? null, topic }),
    onSuccess: (data, topic) => {
      setAnswers((current) => ({
        ...current,
        [topic]: { answer: data.answer, source: data.source },
      }));
    },
    onError: (error: Error, topic) => {
      setAnswers((current) => ({
        ...current,
        [topic]: {
          answer: error.message,
          source: "error",
        },
      }));
    },
    onSettled: () => setActivePrompt(null),
  });

  function reset() {
    setAnswers({});
    setActivePrompt(null);
  }

  return (
    <SlideOver
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="About this plan"
    >
      <div className="stack stack-5">
        {plan ? (
          <div className="stack stack-2">
            <div className="row row-2">
              <span className="mono" style={{ fontWeight: 700 }}>
                {plan.label}
              </span>
              <span className="h4">{plan.title}</span>
            </div>
            <p className="small secondary">{plan.summary}</p>
          </div>
        ) : null}

        <div className="help-panel__prompts">
          {PROMPTS.map((prompt) => {
            const answer = answers[prompt.value];
            const busy = ask.isPending && activePrompt === prompt.value;
            return (
              <div key={prompt.value} className="stack stack-2">
                <button
                  type="button"
                  className="help-prompt"
                  disabled={!tripId || ask.isPending}
                  onClick={() => {
                    setActivePrompt(prompt.value);
                    ask.mutate(prompt.value);
                  }}
                >
                  <span>{prompt.label}</span>
                  <Icon name={busy ? "LoaderCircle" : "ChevronRight"} size={15} className={busy ? "spin" : undefined} />
                </button>
                {answer ? (
                  <div className="help-answer">
                    {answer.answer}
                    <div className="tiny muted" style={{ marginTop: "var(--s-2)" }}>
                      {answer.source === "template"
                        ? "Answered from the plan's structured data."
                        : answer.source === "error"
                          ? ""
                          : "Answered from the plan's structured data and cached."}
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>

        <InlineNote icon="ShieldCheck">
          Answers are generated from the structured plan data only. Nothing here changes a booking.
        </InlineNote>
      </div>
    </SlideOver>
  );
}
