import { ArrowUp, LoaderCircle } from "lucide-react";
import { FormEvent, useState } from "react";

import { Button } from "@/shared/ui/button";
import { Textarea } from "@/shared/ui/textarea";

interface ChatComposerProps {
  loading: boolean;
  onSend: (message: string) => Promise<void>;
}

export function ChatComposer({ loading, onSend }: ChatComposerProps) {
  const [value, setValue] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const text = value.trim();
    if (!text || loading) {
      return;
    }

    setValue("");
    await onSend(text);
  }

  return (
    <form
      className="sticky bottom-0 z-10 bg-paper/95 px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3 backdrop-blur"
      onSubmit={handleSubmit}
    >
      <div className="relative">
        <Textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="例如：6月去东京7天，预算1.2万，2人，偏美食和慢节奏"
          className="min-h-[96px] pr-14"
        />
        <Button
          type="submit"
          size="icon"
          disabled={loading || !value.trim()}
          aria-label="send-message"
          className="absolute bottom-2 right-2 h-10 w-10"
        >
          {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
        </Button>
      </div>
    </form>
  );
}
