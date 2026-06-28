import { Link } from "react-router-dom";
import { BookOpen, List, PenLine, Settings2 } from "lucide-react";
import type { SetupAction } from "../../api";

type Props = {
  bookId: number;
  actions: SetupAction[];
  className?: string;
};

export default function SetupActionBar({ bookId, actions, className = "" }: Props) {
  if (!actions.length) return null;

  return (
    <div className={`mt-2 flex flex-wrap gap-2 ${className}`}>
      {actions.map((action, i) => {
        if (action.type === "write_chapter" && action.chapter_no) {
          return (
            <Link
              key={`${action.type}-${action.chapter_no}-${i}`}
              to={`/books/${bookId}/write/${action.chapter_no}`}
              className="btn-primary text-xs"
            >
              <PenLine className="h-3.5 w-3.5" />
              {action.label}
            </Link>
          );
        }
        if (action.type === "open_outline") {
          return (
            <Link
              key={`${action.type}-${i}`}
              to={`/books/${bookId}/outline`}
              className="btn-secondary text-xs"
            >
              <List className="h-3.5 w-3.5" />
              {action.label}
            </Link>
          );
        }
        if (action.type === "open_overview") {
          return (
            <Link
              key={`${action.type}-${i}`}
              to={`/books/${bookId}`}
              className="btn-secondary text-xs"
            >
              <BookOpen className="h-3.5 w-3.5" />
              {action.label}
            </Link>
          );
        }
        if (action.type === "open_resources") {
          return (
            <Link
              key={`${action.type}-${i}`}
              to={`/books/${bookId}/resources`}
              className="btn-secondary text-xs"
            >
              <Settings2 className="h-3.5 w-3.5" />
              {action.label}
            </Link>
          );
        }
        return null;
      })}
    </div>
  );
}
