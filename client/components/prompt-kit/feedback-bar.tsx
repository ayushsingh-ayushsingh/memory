import { Button, LayerCard } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import { ThumbsDownIcon, ThumbsUpIcon, XIcon } from "@phosphor-icons/react";

type FeedbackBarProps = {
  className?: string;
  title?: string;
  icon?: React.ReactNode;
  onHelpful?: () => void;
  onNotHelpful?: () => void;
  onClose?: () => void;
};

export function FeedbackBar({
  className,
  title,
  icon,
  onHelpful,
  onNotHelpful,
  onClose,
}: FeedbackBarProps) {
  return (
    <LayerCard className={cn("inline-flex px-5 py-4 text-sm", className)}>
      <div className="flex w-full items-center justify-between" role="group" aria-label="Feedback">
        <div className="flex flex-1 items-center justify-start gap-4 pl-4">
          {icon ? (
            <span className="h-lh flex items-center" aria-hidden>
              {icon}
            </span>
          ) : null}
          <span className="font-medium text-kumo-default">{title}</span>
        </div>
        <div className="flex items-center justify-center gap-0.5 px-3 py-0">
          <Button
            variant="ghost"
            size="sm"
            shape="square"
            icon={ThumbsUpIcon}
            aria-label="Helpful"
            title="Helpful"
            onClick={onHelpful}
            className="hover:bg-kumo-tint"
          />
          <Button
            variant="ghost"
            size="sm"
            shape="square"
            icon={ThumbsDownIcon}
            aria-label="Not helpful"
            title="Not helpful"
            onClick={onNotHelpful}
            className="hover:bg-kumo-tint"
          />
        </div>
        <div className="flex items-center justify-center border-l border-kumo-hairline">
          <Button
            variant="ghost"
            size="sm"
            shape="square"
            icon={XIcon}
            aria-label="Close"
            title="Close"
            onClick={onClose}
            className="hover:bg-kumo-tint"
          />
        </div>
      </div>
    </LayerCard>
  );
}
