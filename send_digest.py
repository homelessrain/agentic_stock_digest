"""
This script is used to ask AI API some prompts and then send the daily digest email to the recipient.
"""

import argparse
import os
from datetime import datetime
from pathlib import Path

import anthropic

from utils.email_sender import EmailSender
from utils.html_generator import StockReportHtmlGenerator


class Agent:
    def __init__(self):
        api_key = os.getenv("MODEL_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2)
        self.model = os.getenv("MODEL_KEY")  # e.g. "claude-sonnet-4-6"
        # web search tool is essential for the agent to get the latest information
        self.tools = [{"type": "web_search_20260209", "name": "web_search"}]
        self.reset()

    def prompt(self, new_message: str) -> str:
        if self.responses:
            self.messages.append(
                {"role": "assistant", "content": self.responses[-1]}
            )

        self.messages.append({"role": "user", "content": new_message})
        self.prompt_history.append(new_message)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self.system,
            messages=self.messages,
            tools=self.tools,
        )
        text = self._message_text(response)
        print(text)
        self.responses.append(text)
        return text

    def _message_text(self, response: anthropic.types.Message) -> str:
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        return text

    def reset(self) -> None:
        self.system = "You are a stock market analyst"
        self.messages = []
        self.responses = []
        self.prompt_history = []


def main(args: argparse.Namespace) -> None:

    agent = Agent()
    if args.interactive:
        while True:
            user_input = input("Enter a prompt: ")
            response = agent.prompt(user_input)
            print(response)
    else:
        # Chat with agent
        prompt = f"""
        Today is {datetime.now().strftime("%Y-%m-%d")}. Do the following:
            * Produce a summary of trending US stocks (with their corresponding industry) in the past month
            * Pick the most bullish industry and explain why market is so bullish on it
            * Research on the next technological frontier and the upcoming business context of the industry
            * Based on the research, recommend top 3 stocks of the industry that will benefit from future developments but not priced in yet. Also estimate when the trend will start to be recognized by market and therefore those stocks\' price will pick up.

        Put together a report in markdown format. Add a concise executive summary at the beginning of the report.
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
