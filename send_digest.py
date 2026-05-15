"""
This script is used to ask AI API some prompts and then send the daily digest email to the recipient.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

import anthropic

from utils.email_sender import EmailSender
from utils.html_generator import StockReportHtmlGenerator

# Web search is a server tool: long turns may end with stop_reason "pause_turn" and must be continued.
# See https://platform.claude.com/docs/en/agents-and-tools/tool-use/server-tools
MAX_PAUSE_TURN_CHAINS = 24
# Non-streaming messages.create() rejects large max_tokens (SDK estimates >10m wall time).
# Use streaming below so long digests + web search stay valid. See anthropic-sdk-python "long-requests".
OUTPUT_MAX_TOKENS = 32768
WEB_SEARCH_MAX_USES = 100


class Agent:
    def __init__(self):
        api_key = os.getenv("MODEL_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2)
        self.model = os.getenv("MODEL_KEY")  # e.g. "claude-sonnet-4-6"
        # Server-executed web search; max_uses allows multiple searches in one digest.
        self.tools: list[dict] = [
            {
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": WEB_SEARCH_MAX_USES,
            }
        ]
        self.reset()

    def _create_message_streaming(self) -> anthropic.types.Message:
        """
        Streaming is required for long-running requests (high max_tokens and/or server tools
        like web search). Non-streaming create() raises ValueError from the SDK otherwise.
        """
        with self.client.messages.stream(
            model=self.model,
            max_tokens=OUTPUT_MAX_TOKENS,
            system=self.system,
            messages=self.messages,
            tools=self.tools,
        ) as stream:
            return stream.get_final_message()

    def prompt(self, new_message: str) -> str:
        self.messages.append({"role": "user", "content": new_message})
        self.prompt_history.append(new_message)

        chain: list[anthropic.types.Message] = []
        while len(chain) < MAX_PAUSE_TURN_CHAINS:
            response = self._create_message_streaming()
            chain.append(response)
            self.messages.append({"role": "assistant", "content": response.content})
            print(
                f"[anthropic] segment {len(chain)} stop_reason={response.stop_reason!r}",
                flush=True,
            )
            if response.stop_reason != "pause_turn":
                break
        else:
            print(
                f"[anthropic] warning: hit MAX_PAUSE_TURN_CHAINS ({MAX_PAUSE_TURN_CHAINS}); "
                "response may be incomplete.",
                flush=True,
            )

        text = self._report_text_from_chain(chain)
        print(text, flush=True)
        self.responses.append(text)
        return text

    def _message_text(self, response: anthropic.types.Message) -> str:
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        return text

    def _report_text_from_chain(self, chain: list[anthropic.types.Message]) -> str:
        """Use the last segment that contains text (typically the finished report)."""
        for response in reversed(chain):
            segment = self._message_text(response).strip()
            if segment:
                return self._message_text(response)
        return ""

    def reset(self) -> None:
        self.system = "You are a stock market analyst"
        self.messages: list[dict] = []
        self.responses: list[str] = []
        self.prompt_history: list[str] = []


def main(args: argparse.Namespace) -> None:

    agent = Agent()
    if args.interactive:
        while True:
            user_input = input("Enter a prompt: ")
            agent.prompt(user_input)
    else:
        # Chat with agent
        prompt = f"""
        Today is {datetime.now().strftime("%Y-%m-%d")}. Do the following:
            * Produce a summary of trending US stocks (with their corresponding industry) in the past month
            * Pick the most bullish industry and explain why market is so bullish on it
            * Research on the next technological frontier and the upcoming business context of the industry
            * Based on the research, recommend top 3 stocks of the industry that will benefit from future developments but not priced in yet. Also estimate when the trend will start to be recognized by market and therefore those stocks\' price will pick up.

        Put together a report (just return all the information as text; don't export as a separate md file). Add a concise executive summary at the beginning of the report.
        """
        print(prompt)
        agent.prompt(prompt)

        # Prepare output
        day = datetime.now().strftime("%Y-%m-%d")
        html_gen = StockReportHtmlGenerator(document_title=f"Agentic Stock Digest — {day}")
        html_report = html_gen.to_html_from_responses(agent.responses)
        out_path = Path(f'digest_output/stock_digest_{day}.html')
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_report, encoding="utf-8")
        print(f"Wrote HTML digest to {out_path.resolve()}")

        if args.skip_email:
            print("Skipping email send.")
            return

        # Send email (CI/server uses EMAIL_SENDER / EMAIL_PASSWORD / EMAIL_TO)
        recipients_raw = os.environ.get("EMAIL_TO", "").strip()
        email_sender_addr = os.environ.get("EMAIL_SENDER", "").strip()
        email_password = os.environ.get("EMAIL_PASSWORD")

        if not recipients_raw:
            print("EMAIL_TO not set or empty; skipping email send.")
        elif not email_sender_addr or not email_password:
            print(
                "EMAIL_SENDER and EMAIL_PASSWORD must both be set to send email; skipping."
            )
        else:
            sender = EmailSender(sender=email_sender_addr, password=email_password)
            for recipient in (r.strip() for r in recipients_raw.split(",") if r.strip()):
                sender.send(
                    to=recipient,
                    subject=f"US Stock Digest — {day}",
                    html=html_report,
                )
                print(f"Sent digest email to {recipient}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true", default=False)  # interactive mode is helpful for debugging
    parser.add_argument("--skip_email", action="store_true", default=False)
    args = parser.parse_args()
    main(args)
