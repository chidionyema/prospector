using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class AddPendingDelivery : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "PendingDeliveries",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    EntitlementId = table.Column<long>(type: "INTEGER", nullable: false),
                    PackId = table.Column<string>(type: "TEXT", nullable: false),
                    BuyerEmail = table.Column<string>(type: "TEXT", maxLength: 320, nullable: false),
                    GrantToken = table.Column<string>(type: "TEXT", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false),
                    SentAt = table.Column<DateTime>(type: "TEXT", nullable: true),
                    Attempts = table.Column<int>(type: "INTEGER", nullable: false),
                    LastError = table.Column<string>(type: "TEXT", maxLength: 500, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_PendingDeliveries", x => x.Id);
                    table.ForeignKey(
                        name: "FK_PendingDeliveries_Entitlements_EntitlementId",
                        column: x => x.EntitlementId,
                        principalTable: "Entitlements",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_PendingDeliveries_EntitlementId",
                table: "PendingDeliveries",
                column: "EntitlementId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_PendingDeliveries_SentAt",
                table: "PendingDeliveries",
                column: "SentAt");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "PendingDeliveries");
        }
    }
}
