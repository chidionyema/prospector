using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class InitialCreate : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "Orders",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    PaddleTransactionId = table.Column<string>(type: "TEXT", nullable: false),
                    BuyerEmail = table.Column<string>(type: "TEXT", nullable: false),
                    PackId = table.Column<string>(type: "TEXT", nullable: true),
                    AmountPence = table.Column<long>(type: "INTEGER", nullable: false),
                    Currency = table.Column<string>(type: "TEXT", nullable: false),
                    Country = table.Column<string>(type: "TEXT", nullable: false),
                    Status = table.Column<int>(type: "INTEGER", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Orders", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "Packs",
                columns: table => new
                {
                    Id = table.Column<string>(type: "TEXT", nullable: false),
                    Title = table.Column<string>(type: "TEXT", maxLength: 200, nullable: false),
                    OneLine = table.Column<string>(type: "TEXT", maxLength: 500, nullable: false),
                    PricePence = table.Column<long>(type: "INTEGER", nullable: false),
                    PaddleProductId = table.Column<string>(type: "TEXT", nullable: true),
                    PaddlePriceId = table.Column<string>(type: "TEXT", nullable: true),
                    IsListed = table.Column<bool>(type: "INTEGER", nullable: false),
                    DossierRef = table.Column<string>(type: "TEXT", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false),
                    ContentKey = table.Column<string>(type: "TEXT", nullable: true),
                    ContentHash = table.Column<string>(type: "TEXT", nullable: true),
                    ContentVersion = table.Column<int>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Packs", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "SalesAudits",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    PaddleTransactionId = table.Column<string>(type: "TEXT", nullable: false),
                    PaddleProductId = table.Column<string>(type: "TEXT", nullable: false),
                    AmountPence = table.Column<long>(type: "INTEGER", nullable: false),
                    Currency = table.Column<string>(type: "TEXT", nullable: false),
                    Country = table.Column<string>(type: "TEXT", nullable: false),
                    OccurredAt = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SalesAudits", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "Entitlements",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    OrderId = table.Column<long>(type: "INTEGER", nullable: false),
                    PackId = table.Column<string>(type: "TEXT", nullable: false),
                    BuyerEmail = table.Column<string>(type: "TEXT", nullable: false),
                    GrantToken = table.Column<string>(type: "TEXT", nullable: false),
                    Status = table.Column<int>(type: "INTEGER", nullable: false),
                    ContentKey = table.Column<string>(type: "TEXT", nullable: true),
                    ContentVersion = table.Column<int>(type: "INTEGER", nullable: false),
                    ExpiresAt = table.Column<DateTime>(type: "TEXT", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false),
                    DownloadCount = table.Column<int>(type: "INTEGER", nullable: false),
                    LastDownloadedAt = table.Column<DateTime>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Entitlements", x => x.Id);
                    table.ForeignKey(
                        name: "FK_Entitlements_Orders_OrderId",
                        column: x => x.OrderId,
                        principalTable: "Orders",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_Entitlements_GrantToken",
                table: "Entitlements",
                column: "GrantToken",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Entitlements_OrderId",
                table: "Entitlements",
                column: "OrderId");

            migrationBuilder.CreateIndex(
                name: "IX_Entitlements_PackId",
                table: "Entitlements",
                column: "PackId");

            migrationBuilder.CreateIndex(
                name: "IX_Orders_PaddleTransactionId",
                table: "Orders",
                column: "PaddleTransactionId");

            migrationBuilder.CreateIndex(
                name: "IX_Packs_IsListed",
                table: "Packs",
                column: "IsListed");

            migrationBuilder.CreateIndex(
                name: "IX_SalesAudits_PaddleTransactionId",
                table: "SalesAudits",
                column: "PaddleTransactionId",
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "Entitlements");

            migrationBuilder.DropTable(
                name: "Packs");

            migrationBuilder.DropTable(
                name: "SalesAudits");

            migrationBuilder.DropTable(
                name: "Orders");
        }
    }
}
