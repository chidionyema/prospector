using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class AddWaitlistSignup : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "WaitlistSignups",
                columns: table => new
                {
                    Id = table.Column<string>(type: "TEXT", nullable: false),
                    Email = table.Column<string>(type: "TEXT", maxLength: 320, nullable: false),
                    Query = table.Column<string>(type: "TEXT", maxLength: 500, nullable: true),
                    ConsentVersion = table.Column<string>(type: "TEXT", nullable: false),
                    ConsentTextHash = table.Column<string>(type: "TEXT", nullable: false),
                    IpHash = table.Column<string>(type: "TEXT", nullable: true),
                    Source = table.Column<string>(type: "TEXT", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_WaitlistSignups", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_WaitlistSignups_CreatedAt",
                table: "WaitlistSignups",
                column: "CreatedAt");

            migrationBuilder.CreateIndex(
                name: "IX_WaitlistSignups_Email",
                table: "WaitlistSignups",
                column: "Email");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "WaitlistSignups");
        }
    }
}
