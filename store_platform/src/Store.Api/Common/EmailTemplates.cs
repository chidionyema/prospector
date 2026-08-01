namespace Store.Api.Common;

/// <summary>
/// Transactional email copy and click-through links in one place. Bodies are deliberately plain —
/// inline styles only, no external assets — so they render in every client and the copy can be
/// reviewed without hunting across handlers. Link builders URL-encode the ASP.NET Identity token
/// (which contains +, /, = that would otherwise corrupt the query string) and trim a trailing
/// slash off the configured base so we never emit a double slash.
/// </summary>
public static class EmailTemplates
{
    /// <summary>The verify-email link, e.g.
    /// <c>{base}/account?verify=1&amp;user_id={id}&amp;token={encoded}</c>. The page POSTs these to
    /// <c>/v1/auth/verify-email</c>.</summary>
    /// <remarks>
    /// The introduction-exchange pointed this at a dedicated <c>/verify-email</c> page. The store
    /// has one account route that renders whichever state the query string asks for, so a customer
    /// who has just verified is already looking at the sign-in form rather than a dead end with a
    /// link to it. The explicit <c>verify=1</c> marker is what the page dispatches on — inferring
    /// the mode from which parameters happen to be present would silently change behaviour the
    /// first time any other flow adopted a <c>token</c> parameter.
    /// </remarks>
    public static string VerificationLink(string webBaseUrl, string userId, string token) =>
        $"{webBaseUrl.TrimEnd('/')}/account?verify=1&user_id={Uri.EscapeDataString(userId)}&token={Uri.EscapeDataString(token)}";

    /// <summary>The password-reset link, e.g.
    /// <c>{base}/account?reset=1&amp;email={email}&amp;token={encoded}</c>. Same single-page
    /// dispatch as <see cref="VerificationLink"/>.</summary>
    public static string PasswordResetLink(string webBaseUrl, string email, string token) =>
        $"{webBaseUrl.TrimEnd('/')}/account?reset=1&email={Uri.EscapeDataString(email)}&token={Uri.EscapeDataString(token)}";

    /// <summary>The inert guest pitch page link the target opens, e.g. <c>{base}/pitch/{token}</c>.
    /// The page reveals only the pitch + approved display name + a Sign-in-with-LinkedIn button; the
    /// link carries no clock-start authority (G2/G6) — only the OIDC callback can activate the bridge.</summary>
    public static string PitchLink(string webBaseUrl, string token) =>
        $"{webBaseUrl.TrimEnd('/')}/pitch/{Uri.EscapeDataString(token)}";

    public static (string Subject, string Html) Verification(string verifyLink) => (
        "Verify your email — The Introduction Exchange",
        Wrap("Confirm your email",
            "Thanks for joining The Introduction Exchange. Confirm your email address to activate your account.",
            "Verify email", verifyLink));

    public static (string Subject, string Html) PasswordReset(string resetLink) => (
        "Reset your password — The Introduction Exchange",
        Wrap("Reset your password",
            "We received a request to reset your password. This link expires shortly. If you didn't request it, you can safely ignore this email.",
            "Reset password", resetLink));

    /// <summary>
    /// Sent to the CONNECTOR when the buyer accepts their proposal (E11-006 / WR-001). The platform
    /// never contacts the non-consenting target directly — the connector, who has the genuine
    /// real-world relationship, relays this inert link to their contact. The link reveals only the
    /// pitch + the approved display name; the target accepts by verifying with LinkedIn. The buyer's
    /// identity is never included. <paramref name="targetName"/> is the connector's own approved
    /// display name for the contact (they already know it), used only to make the relay concrete.
    /// </summary>
    public static (string Subject, string Html) PitchRelay(string pitchLink, string? targetName)
    {
        var who = string.IsNullOrWhiteSpace(targetName) ? "your contact" : targetName;
        return (
            "Your introduction was accepted — send the link to your contact",
            Wrap("Your introduction is ready",
                $"Good news — your proposed introduction was accepted. Forward this private link to {who} so they can read the pitch and verify their identity with LinkedIn to accept. The link is inert: it carries no payment, no account access, and cannot start any clock — it only opens the pitch page.",
                "Open the pitch link", pitchLink));
    }

    /// <summary>The buyer's own proposal page, e.g. <c>{base}/proposals/{id}</c>.</summary>
    public static string ProposalLink(string webBaseUrl, Guid bountyId) =>
        $"{webBaseUrl.TrimEnd('/')}/proposals/{bountyId}";

    /// <summary>One-click repost link (D-137), e.g. <c>{base}/proposals/new?repost_from={id}</c>.
    /// The page prefills the form from the voided posting via the authed owner-only GET, so the
    /// link itself grants nothing — a non-owner just gets an empty form.</summary>
    public static string RepostLink(string webBaseUrl, Guid bountyId) =>
        $"{webBaseUrl.TrimEnd('/')}/proposals/new?repost_from={bountyId}";

    /// <summary>
    /// Sent to the BUYER whenever a void releases their reward auth-hold (ghost-void or
    /// unclaimed-expiry). This is the moment the "you are only charged when an introduction is
    /// delivered" promise is kept, so it must be said out loud rather than left for the buyer to
    /// discover on a bank statement. Truth-lock: the reward hold is released, but the posting fee
    /// captured at funding is kept (G9) — the copy claims only what is true and names the fee.
    /// </summary>
    public static (string Subject, string Html) HoldReleased(string proposalLink, string repostLink, string reasonSentence) => (
        "Your reward hold was released",
        Wrap("Your reward hold was released",
            $"{reasonSentence} As promised, the hold on your card for the reward was released automatically and the reward was never captured. Your bank should drop the hold from your statement shortly if it has not already. The posting fee disclosed at funding is separate and is not returned. When you are ready to try again, <a href=\"{repostLink}\" style=\"color:#111\">repost your request in one click</a> and the form will be prefilled with the same brief for a fresh posting.",
            "View your request", proposalLink));

    private static string Wrap(string heading, string body, string cta, string link) =>
        $"""
        <div style="font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;max-width:480px;margin:0 auto;color:#111">
          <h2 style="font-size:20px;margin:0 0 12px">{heading}</h2>
          <p style="font-size:15px;line-height:1.5;margin:0 0 24px">{body}</p>
          <p style="margin:0 0 24px">
            <a href="{link}" style="background:#111;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;font-size:15px;display:inline-block">{cta}</a>
          </p>
          <p style="font-size:13px;color:#666;line-height:1.5;margin:0">If the button doesn't work, paste this link into your browser:<br>{link}</p>
        </div>
        """;
}
