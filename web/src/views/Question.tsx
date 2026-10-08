import * as uiMessages from "../messages";
import { useState } from "react";
import type { Mutate, TaskQuestion, Translate } from "../types";
export default function Question({
  question,
  taskID,
  t,
  busy,
  mutate,
}: {
  question: TaskQuestion;
  taskID: string;
  t: Translate;
  busy: boolean;
  mutate: Mutate;
}) {
  const [answer, setAnswer] = useState("");
  return (
    <form
      className="task-question"
      onSubmit={async (e) => {
        e.preventDefault();
        await mutate(
          `/api/tasks/${taskID}/questions/${question.id}/answer`,
          { answer },
          () => setAnswer(""),
        );
      }}
    >
      <strong>{question.question}</strong>
      {question.options.length > 0 && (
        <div className="task-answer-options">
          {question.options.map((option) => (
            <button
              className={answer === option ? "selected" : ""}
              type="button"
              key={option}
              onClick={() => setAnswer(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      <label className="sr-only" htmlFor={`answer-${question.id}`}>
        {t(...uiMessages.question_your_decision_e9c5ce)}
      </label>
      <textarea
        id={`answer-${question.id}`}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        maxLength={8000}
        rows={2}
      />
      <button className="primary" disabled={busy || !answer.trim()}>
        {t(...uiMessages.question_answer_and_continue_d924d6)}
      </button>
    </form>
  );
}
