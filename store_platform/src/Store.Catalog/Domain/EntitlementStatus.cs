namespace Store.Catalog.Domain;

/// <summary>Whether a download grant is still honoured. Revoked on refund/dispute.</summary>
public enum EntitlementStatus
{
    Active = 0,
    Revoked = 1
}
