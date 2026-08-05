using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class AddPackPriceFloorAndHistory : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<DateTime>(
                name: "MinBillableEffectiveAt",
                table: "Packs",
                type: "TEXT",
                nullable: false,
                defaultValue: new DateTime(1, 1, 1, 0, 0, 0, 0, DateTimeKind.Unspecified));

            migrationBuilder.AddColumn<long>(
                name: "MinBillablePence",
                table: "Packs",
                type: "INTEGER",
                nullable: false,
                defaultValue: 0L);

            // Existing packs are in the steady state: no price change is draining, so their floor
            // is simply their price. EffectiveFloorPence already returns PricePence for them
            // (MinBillableEffectiveAt defaults to 0001-01-01, which is in the past), so the fence
            // is not vacuous even before this runs — but leaving the column at 0 would mean the
            // stored floor reads as "any payment fulfils" to anyone who queries it directly, which
            // is exactly the mistake this pair of columns exists to prevent. Backfill it to the
            // truth rather than relying on every future reader going through the accessor.
            migrationBuilder.Sql("UPDATE Packs SET MinBillablePence = PricePence;");

            migrationBuilder.CreateTable(
                name: "PackPriceHistory",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    PackId = table.Column<string>(type: "TEXT", nullable: false),
                    FromPence = table.Column<long>(type: "INTEGER", nullable: false),
                    ToPence = table.Column<long>(type: "INTEGER", nullable: false),
                    MinBillablePence = table.Column<long>(type: "INTEGER", nullable: false),
                    ProviderPriceId = table.Column<string>(type: "TEXT", maxLength: 255, nullable: true),
                    Reason = table.Column<string>(type: "TEXT", maxLength: 500, nullable: false),
                    Actor = table.Column<string>(type: "TEXT", maxLength: 100, nullable: false),
                    RationaleRef = table.Column<string>(type: "TEXT", maxLength: 500, nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_PackPriceHistory", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_PackPriceHistory_PackId_CreatedAt",
                table: "PackPriceHistory",
                columns: new[] { "PackId", "CreatedAt" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "PackPriceHistory");

            migrationBuilder.DropColumn(
                name: "MinBillableEffectiveAt",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "MinBillablePence",
                table: "Packs");
        }
    }
}
