"use client";

import React from "react";
import { Activity, CircleCheck, FlaskConical, Megaphone, PackagePlus, Plus, ServerCrash, Trash2 } from "lucide-react";

import {
  useDeleteAnnouncement,
  usePostAnnouncement,
  useQosActivity,
  useQosAnnouncements,
} from "@/app/(dashboard)/hooks/qos/useQosHome";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/cva.config";
import { extractErrorMessage } from "@/utils/errorUtils";
import type { QosActivityEvent, QosAnnouncement } from "@/app/(dashboard)/hooks/qos/useQosHome";
import { activityLine, relativeTimeLabel, type ActivityTone } from "./homeData";

const FeedPanel = ({
  icon: Icon,
  title,
  action,
  className,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) => (
  <section
    className={cn(
      "flex max-h-40 min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-xs",
      className,
    )}
  >
    <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b px-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Icon className="size-4 text-muted-foreground" />
        {title}
      </h3>
      {action}
    </header>
    {children !== null && (
      <div
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3"
        role="region"
        aria-label={title}
        tabIndex={0}
      >
        {children}
      </div>
    )}
  </section>
);

const EmptyLine = ({ text }: { text: string }) => (
  <p className="py-3 text-center text-xs text-muted-foreground">{text}</p>
);

const PostAnnouncementDialog = ({
  accessToken,
  open,
  onOpenChange,
}: {
  accessToken: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const [title, setTitle] = React.useState("");
  const [body, setBody] = React.useState("");
  const post = usePostAnnouncement(accessToken);

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    post.mutate(
      { title, body },
      {
        onSuccess: () => {
          setTitle("");
          setBody("");
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Post an announcement</DialogTitle>
            <DialogDescription>Everyone sees it at the top of the home dashboard.</DialogDescription>
          </DialogHeader>
          <label htmlFor="announcement-title" className="flex flex-col gap-1.5 text-sm font-medium">
            Title
            <Input
              id="announcement-title"
              value={title}
              maxLength={120}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label htmlFor="announcement-body" className="flex flex-col gap-1.5 text-sm font-medium">
            Details
            <Textarea
              id="announcement-body"
              value={body}
              maxLength={2000}
              rows={4}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          {post.error !== null && (
            <Alert variant="destructive">
              <AlertDescription>{extractErrorMessage(post.error)}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={title.trim() === "" || post.isPending}>
              Post
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

const DeleteAnnouncementDialog = ({
  accessToken,
  announcement,
  onClose,
}: {
  accessToken: string | null;
  announcement: QosAnnouncement;
  onClose: () => void;
}) => {
  const remove = useDeleteAnnouncement(accessToken);

  return (
    <AlertDialog open onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this announcement?</AlertDialogTitle>
          <AlertDialogDescription>{announcement.title}</AlertDialogDescription>
        </AlertDialogHeader>
        {remove.error !== null && (
          <Alert variant="destructive">
            <AlertDescription>{extractErrorMessage(remove.error)}</AlertDescription>
          </Alert>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => remove.mutate(announcement.id, { onSuccess: onClose })}
          >
            {remove.isPending ? "Deleting..." : "Delete"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};

export const AnnouncementsPanel = ({
  accessToken,
  canManage,
  now,
}: {
  accessToken: string | null;
  canManage: boolean;
  now: Date;
}) => {
  const announcements = useQosAnnouncements(accessToken).data;
  const [posting, setPosting] = React.useState(false);
  const [deleting, setDeleting] = React.useState<QosAnnouncement | null>(null);
  const empty = announcements === undefined || announcements.length === 0;

  return (
    <>
      <FeedPanel
        icon={Megaphone}
        title="Announcements"
        className="max-h-40"
        action={
          <div className="flex items-center gap-2">
            {empty && <span className="text-xs text-muted-foreground">No announcements</span>}
            {canManage && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs text-primary"
                onClick={() => setPosting(true)}
              >
                <Plus className="size-3.5" />
                Post
              </Button>
            )}
          </div>
        }
      >
        {empty ? null : (
          <ul className="flex flex-col gap-3">
            {announcements.map((announcement) => (
              <li key={announcement.id} className="rounded-lg border border-primary/10 bg-primary/5 p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 break-words text-sm font-medium">{announcement.title}</p>
                  {canManage && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6 shrink-0 text-muted-foreground hover:text-destructive"
                      aria-label="Delete announcement"
                      onClick={() => setDeleting(announcement)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  )}
                </div>
                {announcement.body !== "" && (
                  <p className="mt-1 text-xs leading-relaxed whitespace-pre-line break-words text-muted-foreground">
                    {announcement.body}
                  </p>
                )}
                <p className="mt-2 break-words text-[11px] text-muted-foreground">
                  {`${announcement.author} · ${relativeTimeLabel(announcement.created_at, now)}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </FeedPanel>
      <PostAnnouncementDialog accessToken={accessToken} open={posting} onOpenChange={setPosting} />
      {deleting !== null && (
        <DeleteAnnouncementDialog accessToken={accessToken} announcement={deleting} onClose={() => setDeleting(null)} />
      )}
    </>
  );
};

const TONE_BADGE: Readonly<Record<ActivityTone, string>> = {
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  error: "bg-destructive/10 text-destructive",
  info: "bg-primary/10 text-primary",
};

const ACTIVITY_ICON: Readonly<Record<QosActivityEvent["kind"], typeof Activity>> = {
  node_down: ServerCrash,
  node_recovered: CircleCheck,
  benchmark: FlaskConical,
  model_added: PackagePlus,
};

export const ActivityPanel = ({
  accessToken,
  refreshMs,
  now,
}: {
  accessToken: string | null;
  refreshMs: number | false;
  now: Date;
}) => {
  const activity = useQosActivity(accessToken, refreshMs).data;

  return (
    <FeedPanel icon={Activity} title="Activity">
      {activity === undefined || activity.events.length === 0 ? (
        <EmptyLine text="Nothing happened in the last 7 days" />
      ) : (
        <ol className="flex flex-col gap-3">
          {activity.events.map((event, index) => {
            const line = activityLine(event);
            const Icon = ACTIVITY_ICON[event.kind];
            return (
              <li
                key={`${event.kind}-${event.at}-${index}`}
                className="flex gap-2.5 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-right-2 motion-safe:duration-500"
              >
                <span
                  className={cn("flex size-6 shrink-0 items-center justify-center rounded-lg", TONE_BADGE[line.tone])}
                >
                  <Icon className="size-3.5" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="break-words text-xs leading-relaxed font-medium">{line.title}</p>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground" title={line.description}>
                    {`${relativeTimeLabel(event.at, now)} · ${line.description}`}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </FeedPanel>
  );
};
